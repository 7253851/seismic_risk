"""Numerical invariants for controlled GMPE and historical matched response."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))
sys.path.insert(0, str(SCRIPT_ROOT.parents[1] / "plot/shared"))
from Hazard.model import predict_pga
from analysis.Hazard.site_effect_analysis import (
    fixed_gmpe_response, matched_amplification, new_run_directory, prepare_buildings,
    quantile_summary, run_site_effect_analysis, spearman_summary,
)

CONFIG = json.loads((SCRIPT_ROOT / "Hazard/config.json").read_text())["model"]


class SiteEffectTests(unittest.TestCase):
    def fixture(self):
        distance = np.array([0.0, 5.0, 10.0, 15.0])
        frame = pd.DataFrame({
            "Build_ID": [1, 2, 3, 4], "Dom_Fault": ["A", "A", "B", "B"],
            "Dom_Scenario": [13, 13, 22, 22], "Dom_Mw": [6.5, 6.5, 7.9, 7.9],
            "Dom_Rrup": np.sqrt(distance ** 2 + 100),
            "Vs30": [200., 250., 300., 760.], "Dom_Vs30": [200., 250., 300., 760.],
        })
        frame["Vs30_Used_m_s"] = frame.Dom_Vs30
        frame["PGA_Final_g"] = predict_pga(frame.Dom_Mw, frame.Dom_Rrup, frame.Dom_Vs30)[0]
        return frame

    def test_matched_reference_and_site_term_identity(self):
        source = self.fixture()
        result, audit = matched_amplification(source, CONFIG)
        self.assertTrue(audit["supported"])
        self.assertLess(audit["af_site_term_identity_max_error"], 1e-12)
        self.assertEqual(audit["zero_site_a1100_invariance_max_error"], 0)
        self.assertAlmostEqual(result.AF_760.iloc[-1], 1.0)
        self.assertLess(result.AF_760.iloc[0], 1.0)
        pd.testing.assert_frame_equal(source, result[source.columns])

    def test_reference_is_not_a_new_scenario_envelope(self):
        source = self.fixture()
        result, _ = matched_amplification(source, CONFIG)
        expected = predict_pga(source.Dom_Mw, source.Dom_Rrup, 760.)[0]
        np.testing.assert_allclose(result.PGA_Reference_760_g, expected)
        self.assertEqual(result.Dom_Scenario.tolist(), [13, 13, 22, 22])

    def test_replay_mismatch_withholds_af(self):
        source = self.fixture()
        source["PGA_Final_g"] *= 1.1
        result, audit = matched_amplification(source, CONFIG)
        self.assertFalse(audit["supported"])
        self.assertNotIn("AF_760", result)

    def test_unsupported_reference_withholds_af(self):
        restricted = {**CONFIG, "vs30_range": [140., 700.]}
        result, audit = matched_amplification(self.fixture(), restricted)
        self.assertFalse(audit["supported"])
        self.assertNotIn("AF_760", result)

    def test_distance_edges_and_invalid_records(self):
        source = self.fixture()
        valid, excluded = prepare_buildings(source, CONFIG, 5)
        self.assertEqual(valid.Distance_Bin_Index.tolist(), [0, 1, 2, 3])
        self.assertTrue(excluded.empty)
        source.loc[0, "Dom_Vs30"] = -1
        valid, excluded = prepare_buildings(source, CONFIG, 5)
        self.assertEqual(len(valid), 3)
        self.assertEqual(excluded.Build_ID.tolist(), [1])

    def test_ties_and_constant_vs30(self):
        frame = pd.DataFrame({"Vs30_Used_m_s": [250.] * 5, "PGA_Final_g": [.2, .21, .22, .23, .24]})
        correlation = spearman_summary(frame)
        self.assertEqual(correlation["Correlation_Status"], "Constant Vs30")
        self.assertTrue(np.isnan(correlation["Spearman_rho"]))
        table = quantile_summary(frame, "PGA_Final_g", 20)
        self.assertEqual(len(table), 1)
        self.assertEqual(table.Building_Count.sum(), 5)
        frame["Vs30_Used_m_s"] = [200., 200., 200., 200., 300.]
        self.assertEqual(quantile_summary(frame, "PGA_Final_g", 20).Building_Count.sum(), 5)

    def test_runs_reuse_current_directory_and_preserve_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            first = new_run_directory(Path(directory))
            original = first / "existing.txt"
            original.write_text("preserve")
            second = new_run_directory(Path(directory))
            self.assertEqual(first, second)
            self.assertEqual(first.name, "current")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertEqual(original.read_text(), "preserve")

    def test_fixed_response_uses_direct_rrup_without_clipping_or_conversion(self):
        frame, audit = fixed_gmpe_response(CONFIG)
        self.assertEqual(len(frame), 4 * 1161)
        self.assertEqual(frame.Rrup_Input_km.unique().tolist(), [10., 15., 20., 30.])
        self.assertEqual(frame.Mw.unique().tolist(), [6.])
        for distance, group in frame.groupby("Rrup_Input_km"):
            pga = predict_pga(6., distance, group.Vs30_m_s)[0]
            reference = predict_pga(6., distance, 760.)[0]
            np.testing.assert_allclose(group.PGA_g, pga, rtol=1e-13)
            np.testing.assert_allclose(group.AF_760, pga / reference, rtol=1e-13)
            self.assertEqual(group.AF_760.iloc[-1], 1.)
            self.assertTrue(group.A1100_Zero_Site_g.nunique() == 1)
        self.assertNotAlmostEqual(frame.loc[frame.Rrup_Input_km.eq(10), "PGA_g"].iloc[0], frame.loc[frame.Rrup_Input_km.eq(15), "PGA_g"].iloc[0])
        self.assertTrue(all(check["reference_AF"] == 1 for check in audit["per_distance_checks"]))

    def test_fixed_response_all_inputs_within_documented_ranges(self):
        frame, audit = fixed_gmpe_response(CONFIG)
        self.assertFalse(frame.is_mechanism_extrapolated.any())
        self.assertFalse(frame.is_mw_out_of_range.any())
        self.assertFalse(frame.is_rrup_out_of_range.any())
        self.assertFalse(frame.is_any_extrapolation.any())
        self.assertNotIn(5., frame.Rrup_Input_km.unique())
        self.assertEqual(audit["applicability"]["mechanism_specific_Mw_range"], [4.2, 6.1])
        self.assertTrue(audit["applicability"]["all_requested_inputs_in_range"])
        self.assertTrue(audit["applicability"]["ZTOR_in_range"])

    def test_fixed_response_rejects_invalid_ranges_and_unsupported_parameters(self):
        for config in ({**CONFIG, "vs30_range": [200., 1130.]}, {**CONFIG, "mechanism": "reverse"}, {**CONFIG, "hanging_wall": True}, {**CONFIG, "rupture_top_depth_km": 26.}):
            with self.assertRaises(ValueError):
                fixed_gmpe_response(config)
        for velocities in ([180., 760., 500.], [100., 760.], [180., np.nan], [180., 1200.]):
            with self.assertRaises(ValueError):
                fixed_gmpe_response(CONFIG, vs30_values=velocities)
        with self.assertRaises(ValueError):
            fixed_gmpe_response(CONFIG, distances_km=[0, 10])
        for distances in ([5., 10.], [10., 201.]):
            with self.assertRaisesRegex(ValueError, "Rrup is outside"):
                fixed_gmpe_response(CONFIG, distances_km=distances)
        for magnitude in (4., 6.5, 8.):
            with self.assertRaisesRegex(ValueError, "supported strike-slip range"):
                fixed_gmpe_response(CONFIG, magnitude=magnitude)

    def test_unsupported_reference_aborts_before_predicting(self):
        restricted = {**CONFIG, "vs30_range": [140., 700.]}
        with patch("analysis.Hazard.site_effect_analysis.gmpe.predict_pga", autospec=True, side_effect=predict_pga) as predictor:
            with self.assertRaisesRegex(ValueError, "Reference Vs30=760.*no extrapolation allowed"):
                fixed_gmpe_response(restricted)
            predictor.assert_not_called()

    def test_fixed_response_uses_each_distances_own_reference(self):
        frame, _ = fixed_gmpe_response(CONFIG)
        at200 = frame.loc[frame.Vs30_m_s.eq(200)].set_index("Rrup_Input_km")
        self.assertAlmostEqual(at200.loc[10., "AF_760"], 1.0766428742513265, places=12)
        self.assertGreater(at200.loc[30., "AF_760"], at200.loc[10., "AF_760"])
        self.assertNotAlmostEqual(at200.loc[10., "PGA_Reference_760_g"], at200.loc[30., "PGA_Reference_760_g"])

    def test_current_entry_point_defaults_to_controlled_response(self):
        with patch("analysis.Hazard.site_effect_analysis.run_fixed_gmpe_response", return_value={"test": "fixed"}) as controlled:
            result = run_site_effect_analysis(pd.DataFrame({"irrelevant": [1]}))
        controlled.assert_called_once()
        self.assertEqual(result, {"test": "fixed"})


if __name__ == "__main__":
    unittest.main()
