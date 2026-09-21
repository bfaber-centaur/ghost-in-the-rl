package main

import (
	"bufio"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
)

const defaultBase = "https://mimo.xiaomi.com/rl"

type config struct {
	base       string
	out        string
	interval   time.Duration
	watch      bool
	backfill   bool
	seriesSize int
	retries    int
}

type runsResponse struct {
	Runs []struct {
		Key   string `json:"key"`
		Label string `json:"label"`
	} `json:"runs"`
	Pins []string `json:"pins"`
}

type statusResponse struct {
	Version string `json:"version"`
	Run     struct {
		Key  string  `json:"key"`
		Mode string  `json:"mode"`
		End  float64 `json:"end"`
	} `json:"run"`
	Step struct {
		Last int `json:"last"`
	} `json:"step"`
}

type tagsResponse struct {
	Run     string   `json:"run"`
	Version string   `json:"version"`
	Tags    []string `json:"tags"`
}

type event struct {
	CapturedAt string `json:"captured_at"`
	Endpoint   string `json:"endpoint"`
	Run        string `json:"run,omitempty"`
	Version    string `json:"version,omitempty"`
	URL        string `json:"url"`
	Status     int    `json:"status"`
	Bytes      int    `json:"bytes"`
	SHA256     string `json:"sha256,omitempty"`
	Object     string `json:"object,omitempty"`
	Error      string `json:"error,omitempty"`
}

type collector struct {
	cfg        config
	client     *http.Client
	manifest   *os.File
	seenTags   map[string]string // run -> version
	lastStep   map[string]int
	seriesDone map[string]map[string]struct{} // run\x00version -> completed tags
	pins       []string
	sleep      func(context.Context, time.Duration) error
}

func main() {
	var cfg config
	flag.StringVar(&cfg.base, "base", defaultBase, "dashboard base URL")
	flag.StringVar(&cfg.out, "out", "data/mimo", "output directory")
	flag.DurationVar(&cfg.interval, "interval", 30*time.Second, "watch poll interval")
	flag.BoolVar(&cfg.watch, "watch", false, "keep polling live state until interrupted")
	flag.BoolVar(&cfg.backfill, "backfill", true, "fetch all historical metric series once per run/version")
	flag.IntVar(&cfg.seriesSize, "series-batch", 50, "metric tags per /series request")
	flag.IntVar(&cfg.retries, "retries", 4, "retries for transient HTTP failures")
	flag.Parse()

	if cfg.seriesSize < 1 || cfg.seriesSize > 100 {
		fmt.Fprintln(os.Stderr, "-series-batch must be between 1 and 100")
		os.Exit(2)
	}
	if cfg.retries < 0 || cfg.retries > 10 {
		fmt.Fprintln(os.Stderr, "-retries must be between 0 and 10")
		os.Exit(2)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	c, err := newCollector(cfg)
	if err != nil {
		fatal(err)
	}
	defer c.close()

	if err := c.snapshot(ctx); err != nil {
		fatal(err)
	}
	if !cfg.watch {
		return
	}

	fmt.Fprintf(os.Stderr, "watching every %s; Ctrl-C to stop\n", cfg.interval)
	ticker := time.NewTicker(cfg.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := c.pollLive(ctx); err != nil {
				fmt.Fprintf(os.Stderr, "poll: %v\n", err)
			}
		}
	}
}

func newCollector(cfg config) (*collector, error) {
	if err := os.MkdirAll(filepath.Join(cfg.out, "objects"), 0o755); err != nil {
		return nil, err
	}
	manifestPath := filepath.Join(cfg.out, "manifest.ndjson")
	seriesDone, err := loadSeriesCoverage(manifestPath)
	if err != nil {
		return nil, err
	}
	f, err := os.OpenFile(manifestPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}
	return &collector{
		cfg: cfg,
		client: &http.Client{
			Timeout: 20 * time.Second,
		},
		manifest:   f,
		seenTags:   make(map[string]string),
		lastStep:   make(map[string]int),
		seriesDone: seriesDone,
		sleep:      sleepContext,
	}, nil
}

func (c *collector) close() error { return c.manifest.Close() }

func (c *collector) snapshot(ctx context.Context) error {
	var runs runsResponse
	if _, err := c.getJSON(ctx, "runs", "", "", "/api/runs", nil, &runs); err != nil {
		return fmt.Errorf("runs: %w", err)
	}
	c.pins = append([]string(nil), runs.Pins...)

	if _, err := c.getJSON(ctx, "notices", "", "", "/api/notices", nil, nil); err != nil {
		fmt.Fprintf(os.Stderr, "notices: %v\n", err)
	}
	if _, err := c.getJSON(ctx, "benchmarks", "", "", "/api/benchmarks", nil, nil); err != nil {
		fmt.Fprintf(os.Stderr, "benchmarks: %v\n", err)
	}

	var errs []error
	for _, r := range runs.Runs {
		if err := c.snapshotRun(ctx, r.Key); err != nil {
			errs = append(errs, fmt.Errorf("run %s: %w", r.Key, err))
		}
	}
	return errors.Join(errs...)
}

func (c *collector) snapshotRun(ctx context.Context, run string) error {
	var st statusResponse
	q := url.Values{"run": {run}}
	if _, err := c.getJSON(ctx, "status", run, "", "/api/status", q, &st); err != nil {
		return err
	}
	c.lastStep[run] = st.Step.Last

	if _, err := c.getJSON(ctx, "live", run, st.Version, "/api/live", q, nil); err != nil {
		fmt.Fprintf(os.Stderr, "live %s: %v\n", run, err)
	}

	if st.Version == "" {
		return nil
	}
	return c.captureVersion(ctx, run, st.Version)
}

func (c *collector) captureVersion(ctx context.Context, run, version string) error {
	if c.seenTags[run] == version {
		return nil
	}
	q := url.Values{"run": {run}, "v": {version}}
	var tags tagsResponse
	if _, err := c.getJSON(ctx, "tags", run, version, "/api/tags", q, &tags); err != nil {
		return fmt.Errorf("tags: %w", err)
	}
	if !c.cfg.backfill || len(tags.Tags) == 0 {
		c.seenTags[run] = version
		return nil
	}

	pending := c.pendingSeriesTags(run, version, tags.Tags)
	if len(pending) == 0 {
		fmt.Fprintf(os.Stderr, "%s: all %d metrics already captured\n", run, len(tags.Tags))
		c.seenTags[run] = version
		return nil
	}
	fmt.Fprintf(os.Stderr, "%s: backfilling %d/%d uncaptured metrics in batches of %d\n", run, len(pending), len(tags.Tags), c.cfg.seriesSize)

	var errs []error
	for i := 0; i < len(pending); i += c.cfg.seriesSize {
		end := min(i+c.cfg.seriesSize, len(pending))
		if err := c.captureSeriesBatch(ctx, run, version, pending[i:end]); err != nil {
			errs = append(errs, err)
		}
		if err := c.sleep(ctx, 150*time.Millisecond); err != nil {
			return err
		}
	}
	if err := errors.Join(errs...); err != nil {
		return err
	}
	c.seenTags[run] = version
	return nil
}

func (c *collector) pendingSeriesTags(run, version string, tags []string) []string {
	done := c.seriesDone[seriesKey(run, version)]
	if len(done) == 0 {
		return append([]string(nil), tags...)
	}
	pending := make([]string, 0, len(tags))
	for _, tag := range tags {
		if _, ok := done[tag]; !ok {
			pending = append(pending, tag)
		}
	}
	return pending
}

func (c *collector) captureSeriesBatch(ctx context.Context, run, version string, tags []string) error {
	if len(tags) == 0 {
		return nil
	}
	q := url.Values{
		"run":  {run},
		"v":    {version},
		"tags": {strings.Join(tags, ",")},
	}
	if _, err := c.getJSON(ctx, "series", run, version, "/api/series", q, nil); err == nil {
		c.markSeriesDone(run, version, tags)
		return nil
	} else if len(tags) == 1 {
		return fmt.Errorf("series tag %q: %w", tags[0], err)
	} else {
		mid := len(tags) / 2
		fmt.Fprintf(os.Stderr, "%s: splitting failed /series batch of %d tags into %d+%d\n", run, len(tags), mid, len(tags)-mid)
		leftErr := c.captureSeriesBatch(ctx, run, version, tags[:mid])
		rightErr := c.captureSeriesBatch(ctx, run, version, tags[mid:])
		return errors.Join(leftErr, rightErr)
	}
}

func (c *collector) markSeriesDone(run, version string, tags []string) {
	key := seriesKey(run, version)
	if c.seriesDone[key] == nil {
		c.seriesDone[key] = make(map[string]struct{})
	}
	for _, tag := range tags {
		c.seriesDone[key][tag] = struct{}{}
	}
}

func (c *collector) pollLive(ctx context.Context) error {
	var runs runsResponse
	if _, err := c.getJSON(ctx, "runs", "", "", "/api/runs", nil, &runs); err != nil {
		return err
	}
	if len(runs.Pins) > 0 {
		c.pins = append(c.pins[:0], runs.Pins...)
	}

	if _, err := c.getJSON(ctx, "notices", "", "", "/api/notices", nil, nil); err != nil {
		fmt.Fprintf(os.Stderr, "notices: %v\n", err)
	}
	if _, err := c.getJSON(ctx, "benchmarks", "", "", "/api/benchmarks", nil, nil); err != nil {
		fmt.Fprintf(os.Stderr, "benchmarks: %v\n", err)
	}

	for _, r := range runs.Runs {
		run := r.Key
		q := url.Values{"run": {run}}
		var st statusResponse
		if _, err := c.getJSON(ctx, "status", run, "", "/api/status", q, &st); err != nil {
			fmt.Fprintf(os.Stderr, "status %s: %v\n", run, err)
			continue
		}
		if _, err := c.getJSON(ctx, "live", run, st.Version, "/api/live", q, nil); err != nil {
			fmt.Fprintf(os.Stderr, "live %s: %v\n", run, err)
		}
		if st.Version != "" && c.seenTags[run] != st.Version {
			if err := c.captureVersion(ctx, run, st.Version); err != nil {
				fmt.Fprintf(os.Stderr, "version %s %s: %v\n", run, st.Version, err)
			}
		}
		if prev, ok := c.lastStep[run]; !ok || prev != st.Step.Last {
			c.lastStep[run] = st.Step.Last
			if len(c.pins) > 0 && st.Version != "" {
				q := url.Values{
					"run":  {run},
					"v":    {st.Version},
					"tags": {strings.Join(c.pins, ",")},
				}
				if _, err := c.getJSON(ctx, "series-pins", run, st.Version, "/api/series", q, nil); err != nil {
					fmt.Fprintf(os.Stderr, "series-pins %s: %v\n", run, err)
				}
			}
		}
	}
	return nil
}

func (c *collector) getJSON(ctx context.Context, endpoint, run, version, path string, q url.Values, dst any) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt <= c.cfg.retries; attempt++ {
		body, retry, err := c.getJSONOnce(ctx, endpoint, run, version, path, q, dst)
		if err == nil {
			return body, nil
		}
		lastErr = err
		if !retry || attempt == c.cfg.retries {
			break
		}
		delay := retryDelay(attempt)
		fmt.Fprintf(os.Stderr, "%s: transient failure (%v); retrying in %s\n", endpoint, err, delay)
		if err := c.sleep(ctx, delay); err != nil {
			return nil, err
		}
	}
	return nil, lastErr
}

func (c *collector) getJSONOnce(ctx context.Context, endpoint, run, version, path string, q url.Values, dst any) ([]byte, bool, error) {
	u := strings.TrimRight(c.cfg.base, "/") + path
	if len(q) > 0 {
		u += "?" + q.Encode()
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, false, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "mimo-capture/0.2 (+research snapshotter)")

	resp, err := c.client.Do(req)
	if err != nil {
		_ = c.writeEvent(event{
			CapturedAt: time.Now().UTC().Format(time.RFC3339Nano),
			Endpoint:   endpoint, Run: run, Version: version, URL: u, Error: err.Error(),
		})
		return nil, true, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, true, err
	}

	ev := event{
		CapturedAt: time.Now().UTC().Format(time.RFC3339Nano),
		Endpoint:   endpoint, Run: run, Version: version, URL: u,
		Status: resp.StatusCode, Bytes: len(body),
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		ev.Error = strings.TrimSpace(string(body))
		_ = c.writeEvent(ev)
		return nil, retryableStatus(resp.StatusCode), fmt.Errorf("HTTP %d: %s", resp.StatusCode, truncate(ev.Error, 300))
	}
	if !json.Valid(body) {
		ev.Error = "response is not valid JSON"
		_ = c.writeEvent(ev)
		return nil, true, errors.New(ev.Error)
	}

	sha := sha256.Sum256(body)
	h := hex.EncodeToString(sha[:])
	objRel := filepath.ToSlash(filepath.Join("objects", h+".json.gz"))
	objAbs := filepath.Join(c.cfg.out, filepath.FromSlash(objRel))
	if err := writeGzipOnce(objAbs, body); err != nil {
		return nil, false, err
	}
	ev.SHA256 = h
	ev.Object = objRel
	if err := c.writeEvent(ev); err != nil {
		return nil, false, err
	}

	if dst != nil {
		if err := json.Unmarshal(body, dst); err != nil {
			return nil, false, fmt.Errorf("decode %s: %w", endpoint, err)
		}
	}
	return body, false, nil
}

func retryableStatus(status int) bool {
	switch status {
	case http.StatusRequestTimeout, http.StatusTooManyRequests,
		http.StatusInternalServerError, http.StatusBadGateway,
		http.StatusServiceUnavailable, http.StatusGatewayTimeout:
		return true
	default:
		return false
	}
}

func retryDelay(attempt int) time.Duration {
	// 500ms, 1s, 2s, 4s, ... capped at 8s.
	d := 500 * time.Millisecond * time.Duration(1<<min(attempt, 4))
	if d > 8*time.Second {
		return 8 * time.Second
	}
	return d
}

func sleepContext(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

func loadSeriesCoverage(manifestPath string) (map[string]map[string]struct{}, error) {
	coverage := make(map[string]map[string]struct{})
	f, err := os.Open(manifestPath)
	if errors.Is(err, os.ErrNotExist) {
		return coverage, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()

	s := bufio.NewScanner(f)
	buf := make([]byte, 64*1024)
	s.Buffer(buf, 2<<20)
	line := 0
	for s.Scan() {
		line++
		if len(strings.TrimSpace(s.Text())) == 0 {
			continue
		}
		var ev event
		if err := json.Unmarshal(s.Bytes(), &ev); err != nil {
			return nil, fmt.Errorf("parse %s line %d: %w", manifestPath, line, err)
		}
		if ev.Endpoint != "series" || ev.Status < 200 || ev.Status >= 300 || ev.Run == "" || ev.Version == "" {
			continue
		}
		u, err := url.Parse(ev.URL)
		if err != nil {
			continue
		}
		tags := strings.Split(u.Query().Get("tags"), ",")
		key := seriesKey(ev.Run, ev.Version)
		if coverage[key] == nil {
			coverage[key] = make(map[string]struct{})
		}
		for _, tag := range tags {
			if tag != "" {
				coverage[key][tag] = struct{}{}
			}
		}
	}
	if err := s.Err(); err != nil {
		return nil, err
	}
	return coverage, nil
}

func seriesKey(run, version string) string { return run + "\x00" + version }

func (c *collector) writeEvent(ev event) error {
	b, err := json.Marshal(ev)
	if err != nil {
		return err
	}
	if _, err := c.manifest.Write(append(b, '\n')); err != nil {
		return err
	}
	return c.manifest.Sync()
}

func writeGzipOnce(path string, body []byte) error {
	if _, err := os.Stat(path); err == nil {
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	zw := gzip.NewWriter(f)
	_, werr := zw.Write(body)
	cerr := zw.Close()
	ferr := f.Close()
	if werr != nil {
		_ = os.Remove(tmp)
		return werr
	}
	if cerr != nil {
		_ = os.Remove(tmp)
		return cerr
	}
	if ferr != nil {
		_ = os.Remove(tmp)
		return ferr
	}
	if err := os.Rename(tmp, path); err != nil {
		if errors.Is(err, os.ErrExist) {
			_ = os.Remove(tmp)
			return nil
		}
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "mimo-capture:", err)
	os.Exit(1)
}

// Keep output deterministic in tests/helpers that may inspect URL batches later.
func sortedCopy(xs []string) []string {
	y := append([]string(nil), xs...)
	sort.Strings(y)
	return y
}
