"""The existing five-clinic workload with front-desk day/week scheduling reads.

Only run against an explicitly marked independent synthetic rehearsal. The
underlying runner preserves its target checks, twenty sessions and 80/20 ratio.
"""
import argparse
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import multiclinic_load

def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--schedule-day',required=True,type=date.fromisoformat)
    options,remaining=parser.parse_known_args()
    day=options.schedule_day.isoformat()
    multiclinic_load.READS['FRONT_DESK']=(
        '/scheduling/calendar/?mode=day&day='+day,
        '/scheduling/calendar/?mode=week&day='+day,
        '/slots/','/patients/','/visits/','/finance/receivables/','/frontdesk/')
    sys.argv=[sys.argv[0],*remaining]
    return multiclinic_load.main()

if __name__=='__main__':raise SystemExit(main())
