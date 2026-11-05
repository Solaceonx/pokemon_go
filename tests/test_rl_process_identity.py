"""PowerShell JSON date auto-conversion must preserve process birth timestamps."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path


class ProcessIdentityDates(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell runtime unavailable")
    def test_string_json_datetime_and_offset_preserve_the_same_instant(self):
        helper = Path(__file__).resolve().parents[1] / "scripts/rl_process_identity.ps1"
        literal = str(helper).replace("'", "''")
        code = (f". '{literal}'; "
                "$rlIso='2026-11-02T17:54:35.3238286Z'; "
                "$rlJson=('{\"started_utc\":\"'+$rlIso+'\"}' | ConvertFrom-Json); "
                "$rlInputs=@($rlIso,$rlJson.started_utc,[DateTimeOffset]::Parse($rlIso)); "
                "@($rlInputs | ForEach-Object { (Convert-RlRecordedStartToUtc $_).ToString('o') }) "
                "| ConvertTo-Json -Compress")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", code],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["2026-11-02T17:54:35.3238286Z"] * 3)


if __name__ == "__main__":
    unittest.main()
