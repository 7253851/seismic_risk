"""Scientific invariants and parity with the supplied supplementary method."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Validation.gnss_velocity import (slopes, time_axis, parse_date_column,
                                     haversine_km, increment_metrics, pair_metrics,
                                     rank_candidates, run_scene)

ROOT = Path(__file__).resolve().parents[3]


class GNSSVelocityTests(unittest.TestCase):
    def dates(self):
        return pd.date_range("2017-01-10", periods=36, freq="22D")

    def test_known_rate_and_constant_offset_invariance(self):
        dates = self.dates()
        t = time_axis(dates)
        np.testing.assert_allclose(slopes(np.array([3*t+50, -2*t-8]), dates), [3, -2], atol=1e-10)
        np.testing.assert_allclose(slopes(3*t, dates), slopes(3*t+5000, dates), atol=1e-10)

    @unittest.skipUnless((ROOT/"Supplementary_experiments/Script/05GNSS_PS_U_valid.py").is_file(),
                         "Original supplementary script is absent; current numerical-invariant tests remain active")
    def test_parity_with_original_rate_and_lag_functions(self):
        source = ROOT/"Supplementary_experiments/Script/05GNSS_PS_U_valid.py"
        spec = importlib.util.spec_from_file_location("original_gnss_validation", source)
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        rng = np.random.default_rng(193)
        dates = self.dates().to_numpy()
        g = np.cumsum(rng.normal(size=36))
        p = np.vstack([g*.9+rng.normal(size=36), g+50])
        expected = original.compute_chunk_trend_scores(p, g, dates, np.ones(2), "ref0")
        np.testing.assert_allclose(slopes(p, dates), expected[0], atol=1e-12)
        for row in p:
            old_r, old_rmse, old_lag = original.pearson_rmse_delta_1d(g-g[0], row-row[0], True, 1)
            new = increment_metrics(g, row, 1)
            self.assertAlmostEqual(new['r_delta'], old_r)
            self.assertAlmostEqual(new['RMSE_delta'], old_rmse)
            self.assertEqual(new['lag_used'], old_lag)

    def test_dates_and_incomplete_rows(self):
        self.assertEqual(parse_date_column("F2017_1_5_0_00"), pd.Timestamp("2017-01-05"))
        self.assertEqual(parse_date_column("F2017_1_10"), pd.Timestamp("2017-01-10"))
        self.assertIsNone(parse_date_column("Field1"))
        data = np.ones(36)
        data[4] = np.nan
        self.assertTrue(np.isnan(slopes(data, self.dates())[0]))
        with self.assertRaises(ValueError):
            time_axis(["2017-01-01", "2017-01-01"])

    def test_distance_and_combined_sort(self):
        self.assertAlmostEqual(float(haversine_km(102.8, 25.03, 102.8, 25.03)), 0)
        frame = pd.DataFrame({"PS_ID": [1, 2, 3], "trend_score": [.1, .2, .1], "distance_km": [10, 0, 2]})
        ranked = rank_candidates(frame, .3)
        self.assertEqual(ranked.PS_ID.tolist(), [3, 1, 2])
        self.assertEqual(ranked['rank'].tolist(), [1, 2, 3])

    def test_metrics_do_not_fit_away_bias_or_change_units(self):
        g = np.arange(36, dtype=float)
        result = pair_metrics(g, g+4)
        self.assertEqual(result['rmse_mm'], 4)
        self.assertEqual(result['bias_mm'], 4)
        self.assertAlmostEqual(result['pearson_r'], 1)
        self.assertIsNone(pair_metrics(g, np.zeros(36))['pearson_r'])

    def test_sql_pipeline_preserves_ids_los_conversion_and_filters(self):
        dates = self.dates()
        t = time_axis(dates)-time_axis(dates)[0]
        columns = [f'F{d.year}_{d.month}_{d.day}' for d in dates]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            g = 4*t
            gnss_path = directory/'gnss.csv'
            pd.DataFrame({'date_insar': dates, 'gnss_u_ref0': g}).to_csv(gnss_path, index=False)
            daily = directory/'daily.csv'
            pd.DataFrame({'date': dates, 'U_rel_mm': g}).to_csv(daily, index=False)
            frame = pd.DataFrame({'fid': [1, 2, 3, 4], 'Field1': [101, 102, 103, 104],
                                  'lon': [102.8]*4, 'lat': [25.03]*4, 'v': [2]*4,
                                  'inc': [.6]*4, 'coh': [.95, .3, .95, .95]})
            for j, col in enumerate(columns):
                frame[col] = np.array([4.1, 4, -4, 10])*t[j]*np.cos(.6)
            config = {'inputs': {'gnss_daily': str(daily)}, 'selection': {
                'coherence_min': .8, 'top_n': 1, 'require_same_trend_sign': True,
                'distance_weight': .3, 'allow_increment_lag': True,
                'max_increment_lag': 1, 'chunk_size': 2}}
            with sqlite3.connect(':memory:') as connection:
                frame.to_sql('TEST_PS', connection, index=False)
                summary, audit = run_scene(connection, {'name': 'TEST', 'layer': 'TEST_PS', 'gnss_series': str(gnss_path)},
                                           config, pd.Series({'lon': 102.8, 'lat': 25.03}), directory)
                self.assertEqual(summary['top1_PS_ID'], 101)
                self.assertAlmostEqual(summary['top1_ps_rate_mm_yr'], 4.1)
                self.assertEqual(audit['filter_counts']['coherence_pass'], 3)
                self.assertEqual(audit['filter_counts']['same_sign_pass'], 2)
                pd.testing.assert_frame_equal(pd.read_sql('SELECT * FROM TEST_PS', connection), frame)
            result = pd.read_csv(directory/'TEST_Top10_Complete.csv')
            np.testing.assert_allclose(result[columns].to_numpy()[0], 4.1*t)
            self.assertAlmostEqual(result.v_vertical_stored.iloc[0], 2/np.cos(.6))


if __name__ == '__main__':
    unittest.main()
