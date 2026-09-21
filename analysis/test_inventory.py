"""Synthetic archives using shapes inspected in the 2026-09-21 capture."""
import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from inventory import ArchiveError, analyze, digest, write_outputs


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'archive'
        (self.root / 'objects').mkdir(parents=True)
        self.manifest = self.root / 'manifest.ndjson'
        self.manifest.touch()
        self.events = []

    def add(self, endpoint, data, run='pro', version='v1', requested=None):
        body = json.dumps(data).encode()
        sha = digest(body)
        relative = f'objects/{sha}.json.gz'
        (self.root / relative).write_bytes(gzip.compress(body, mtime=0))
        query = urlencode({'run': run, 'v': version, 'tags': ','.join(requested or [])})
        event = dict(endpoint=endpoint, run=run, version=version, status=200,
                     captured_at='2026-09-21T05:00:00Z', bytes=len(body), sha256=sha,
                     object=relative, url='https://example.invalid/api/' + endpoint + '?' + query)
        self.events.append(event)
        self.flush()
        return event

    def flush(self):
        self.manifest.write_text(''.join(json.dumps(e)+'\n' for e in self.events))

    def tags(self, tags, version='v1'):
        self.add('tags', dict(run='pro', version=version, tags=tags), version=version)

    def series(self, values, version='v1', steps=None, walls=None, requested=None):
        self.add('series', dict(run='pro', version=version, steps=steps or [1, 2],
                               walls=walls or [1789468300., 1789468400.], series=values),
                 version=version, requested=requested if requested is not None else list(values))

    def test_successful_request_does_not_prove_returned_coverage(self):
        self.tags(['a', 'b', 'c'])
        self.series({'a': [0, None], 'b': []}, requested=['a', 'b', 'c'])
        inv, _ = analyze(self.root)
        g = inv['groups'][0]
        self.assertEqual(g['requested_count'], 3)
        self.assertEqual(g['returned_count'], 2)
        self.assertEqual(g['missing_tags'], ['c'])
        self.assertEqual(g['empty_tags'], ['b'])
        self.assertEqual(g['with_nonnull_count'], 1)
        self.assertEqual(inv['metrics'][0]['null_count'], 1)
        self.assertEqual(inv['metrics'][0]['min_value'], 0)
        self.assertEqual(inv['metrics'][0]['null_only_steps'], [2])

    def test_duplicates_conflicts_and_versions(self):
        self.tags(['a'])
        self.series({'a': [1, None]})
        self.series({'a': [1, None]})
        self.series({'a': [2, None]})
        self.tags(['a'], 'v2')
        self.series({'a': [3, None]}, 'v2')
        inv, _ = analyze(self.root)
        first, second = inv['metrics']
        self.assertEqual(first['exact_duplicate_count'], 3)
        self.assertEqual(first['unique_coordinate_count'], 2)
        self.assertEqual(first['point_count'], 3)
        self.assertEqual(first['conflict_count'], 1)
        self.assertEqual(len(first['conflicts'][0]['variants']), 2)
        self.assertEqual(second['conflict_count'], 0)
        self.assertEqual(second['min_value'], 3)

    def test_live_does_not_extend_historical_grid_and_benchmark_stays_untimed(self):
        self.tags(['a'])
        self.series({'a': [0, 1]})
        self.add('live', dict(log_time=1789468500., latest=dict(t=1789468500., step=31, accept=4), entries=[]))
        self.add('benchmarks', dict(benchmarks=[dict(key='bench', title='Bench', results={'pro': {'2': 5.0}})]), run='', version='')
        inv, timeline = analyze(self.root)
        self.assertEqual(inv['groups'][0]['observed_steps'], [1, 2])
        live = next(r for r in timeline if r['event_kind'] == 'live_latest')
        self.assertEqual(live['completion_state'], 'sampler_only')
        benchmark = next(r for r in timeline if r['event_kind'] == 'benchmark')
        self.assertIsNone(benchmark['source_time_raw'])
        self.assertEqual(benchmark['version'], '')
        self.assertEqual(live['sources'][0]['json_pointer'], '/latest')

    def test_status_version_comes_from_payload_and_notice_scope_stays_null(self):
        self.add('status', dict(run=dict(key='pro', start=1789468200., end=1789468600., mode='ended'),
                               version='payload-version', step=dict(last=2), totals=dict(restarts=5),
                               events=[dict(t=1789468400., kind='step', step=2)]), version='')
        self.add('notices', dict(notices=[dict(t=1789468450., run=None, text='pro restarted')]), run='', version='')
        inv, timeline = analyze(self.root)
        self.assertEqual(inv['groups'][0]['version'], 'payload-version')
        self.assertEqual(next(r for r in timeline if r['event_kind']=='notice')['run'], '')

    def test_bad_hash_byte_count_and_missing_object(self):
        self.tags(['a'])
        original = dict(self.events[0])
        for change in ({'sha256': '0'*64}, {'bytes': 1}, {'object': 'objects/missing.json.gz'}):
            with self.subTest(change=change):
                self.events[0] = {**original, **change}
                self.flush()
                with self.assertRaises(ArchiveError):
                    analyze(self.root)

    def test_redone_steps_preserve_both_status_occurrences(self):
        self.tags(['a'])
        self.series({'a': [1, 2]}, steps=[16, 17])
        self.add('status', dict(run=dict(key='pro'), version='v1', step=dict(last=17),
                               totals=dict(restarts=1), events=[
                                   dict(t=1789468000., kind='step', step=16, redo=False),
                                   dict(t=1789468300., kind='step', step=16, redo=True)]), version='')
        inv, timeline = analyze(self.root)
        checks = inv['groups'][0]['status_step_clock_checks']
        self.assertEqual([c['result'] for c in checks], ['not_in_series', 'exact_match'])
        self.assertEqual([c['redo'] for c in checks], [False, True])
        self.assertEqual(len([r for r in timeline if r['event_kind']=='status_step']), 2)

    def test_corrupt_gzip(self):
        self.tags(['a'])
        (self.root / self.events[0]['object']).write_bytes(b'not gzip')
        with self.assertRaises(ArchiveError):
            analyze(self.root)

    def test_object_path_must_stay_inside_archive(self):
        self.tags(['a'])
        self.events[0]['object'] = '../outside.gz'
        self.flush()
        with self.assertRaisesRegex(ArchiveError, 'escapes archive'):
            analyze(self.root)

    def test_schema_errors_do_not_silently_drop_values(self):
        for value in ([1], [True, 2], [float('nan'), 2]):
            with self.subTest(value=value):
                self.events = []
                self.series({'a': value})
                with self.assertRaises(ArchiveError):
                    analyze(self.root)

    def test_mismatched_identity(self):
        self.add('tags', dict(run='flash', version='v1', tags=['a']))
        with self.assertRaisesRegex(ArchiveError, 'mismatch'):
            analyze(self.root)

    def test_unknown_endpoint(self):
        self.add('new-endpoint', {})
        with self.assertRaisesRegex(ArchiveError, 'unrecognized endpoint'):
            analyze(self.root)

    def test_failed_requests_and_changing_catalog_are_visible(self):
        self.tags(['a'])
        self.tags(['a', 'b'])
        self.events.append(dict(endpoint='series', captured_at='2026-09-21T05:00:00Z', status=502))
        self.flush()
        inv, _ = analyze(self.root)
        self.assertEqual(inv['archive']['failed_entries'], 1)
        self.assertTrue(inv['groups'][0]['catalog_conflict'])

    def test_multiple_wall_times_and_all_null_series(self):
        self.tags(['a'])
        self.series({'a': [None, None]})
        self.series({'a': [None, None]}, walls=[1789468301., 1789468400.])
        inv, _ = analyze(self.root)
        self.assertEqual(inv['groups'][0]['all_null_tags'], ['a'])
        self.assertEqual(inv['metrics'][0]['multiple_wall_steps'], [1])

    def test_outputs_are_deterministic_and_csv_roundtrips(self):
        self.tags(['a/one,two'])
        self.series({'a/one,two': [0, None]})
        first, timeline = analyze(self.root)
        out = Path(self.temp.name) / 'out'
        write_outputs(first, timeline, out)
        original = {p.name: p.read_bytes() for p in out.iterdir()}
        second, timeline2 = analyze(self.root)
        write_outputs(second, timeline2, out)
        self.assertEqual(original, {p.name:p.read_bytes() for p in out.iterdir()})
        with (out / 'metric-families.csv').open() as f:
            row = next(csv.DictReader(f))
            self.assertEqual(row['tag'], 'a/one,two')
            self.assertEqual(json.loads(row['null_only_steps']), [2])


if __name__ == '__main__':
    unittest.main()
