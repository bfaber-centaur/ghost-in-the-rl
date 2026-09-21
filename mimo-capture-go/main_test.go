package main

import (
	"compress/gzip"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestWriteGzipOnce(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "x.json.gz")
	want := []byte(`{"hello":"world"}`)
	if err := writeGzipOnce(p, want); err != nil {
		t.Fatal(err)
	}
	if err := writeGzipOnce(p, []byte(`different`)); err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(p)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	zr, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(want) {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestSortedCopyDoesNotMutate(t *testing.T) {
	x := []string{"b", "a"}
	y := sortedCopy(x)
	if x[0] != "b" || y[0] != "a" {
		t.Fatalf("x=%v y=%v", x, y)
	}
}

func TestLoadSeriesCoverage(t *testing.T) {
	d := t.TempDir()
	manifest := filepath.Join(d, "manifest.ndjson")
	body := strings.Join([]string{
		`{"endpoint":"series","run":"pro","version":"v1","url":"https://example/api/series?run=pro&v=v1&tags=a%2Cb","status":200}`,
		`{"endpoint":"series","run":"pro","version":"v1","url":"https://example/api/series?run=pro&v=v1&tags=c","status":502}`,
		`{"endpoint":"status","run":"pro","version":"v1","url":"https://example/api/status?run=pro","status":200}`,
	}, "\n") + "\n"
	if err := os.WriteFile(manifest, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := loadSeriesCoverage(manifest)
	if err != nil {
		t.Fatal(err)
	}
	set := got[seriesKey("pro", "v1")]
	for _, tag := range []string{"a", "b"} {
		if _, ok := set[tag]; !ok {
			t.Fatalf("missing covered tag %q: %v", tag, set)
		}
	}
	if _, ok := set["c"]; ok {
		t.Fatal("failed request should not count as covered")
	}
}

func TestGetJSONRetriesTransientFailure(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			http.Error(w, "temporary", http.StatusBadGateway)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"ok":true}`)
	}))
	defer srv.Close()

	c := newTestCollector(t, srv.URL, 1)
	c.sleep = func(context.Context, time.Duration) error { return nil }
	if _, err := c.getJSON(context.Background(), "test", "", "", "/x", nil, nil); err != nil {
		t.Fatal(err)
	}
	if got := calls.Load(); got != 2 {
		t.Fatalf("calls=%d want 2", got)
	}
}

func TestCaptureSeriesBatchSplitsPersistentFailure(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		tags := strings.Split(r.URL.Query().Get("tags"), ",")
		if len(tags) > 2 {
			http.Error(w, "too big", http.StatusBadGateway)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"series":{}}`)
	}))
	defer srv.Close()

	c := newTestCollector(t, srv.URL, 0)
	c.sleep = func(context.Context, time.Duration) error { return nil }
	tags := []string{"a", "b", "c", "d"}
	if err := c.captureSeriesBatch(context.Background(), "pro", "v1", tags); err != nil {
		t.Fatal(err)
	}
	for _, tag := range tags {
		if _, ok := c.seriesDone[seriesKey("pro", "v1")][tag]; !ok {
			t.Fatalf("tag %q not marked done", tag)
		}
	}
	if got := calls.Load(); got != 3 {
		t.Fatalf("calls=%d want 3 (failed 4-tag request + two successful halves)", got)
	}
}

func TestPendingSeriesTagsResumesAcrossBatchShapes(t *testing.T) {
	c := &collector{seriesDone: map[string]map[string]struct{}{
		seriesKey("pro", "v1"): {"a": {}, "c": {}},
	}}
	got := c.pendingSeriesTags("pro", "v1", []string{"a", "b", "c", "d"})
	want := []string{"b", "d"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got %v want %v", got, want)
	}
}

func newTestCollector(t *testing.T, base string, retries int) *collector {
	t.Helper()
	d := t.TempDir()
	if err := os.MkdirAll(filepath.Join(d, "objects"), 0o755); err != nil {
		t.Fatal(err)
	}
	mf, err := os.OpenFile(filepath.Join(d, "manifest.ndjson"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { mf.Close() })
	return &collector{
		cfg:        config{base: base, out: d, retries: retries},
		client:     &http.Client{},
		manifest:   mf,
		seenTags:   make(map[string]string),
		lastStep:   make(map[string]int),
		seriesDone: make(map[string]map[string]struct{}),
		sleep:      sleepContext,
	}
}
