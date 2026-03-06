"""
Full audit of goalie saves strategies — all 14 checks.

Re-exports from audit_checks, audit_reporting, and audit_utils.
"""

from audit_checks import check1, check2, check3, check4, check5  # noqa: F401
from audit_reporting import check10_11, check12_13_14  # noqa: F401
from audit_strategy import check6789  # noqa: F401
from audit_utils import load_matrix  # noqa: F401


def main():
    print("Loading feature matrix...")
    df = load_matrix()

    check1(df)
    check2(df)
    check3(df)
    check4(df)
    check5(df)
    mf3_bets, mf2_bets = check6789(df)
    check10_11(df, mf3_bets, mf2_bets)
    check12_13_14(df, mf3_bets, mf2_bets)

    print("=" * 70)
    print("AUDIT COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
