package main

import (
	"compress/gzip"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestWriteGzipOnce(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "x.json.gz")
	want := []byte(`{"hello":"world"}`)
	if err := writeGzipOnce(p, want); err != nil {
		t.Fatal(err)
	}
	// A duplicate content-addressed write should be a no-op.
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
