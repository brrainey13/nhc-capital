"""Diagnostic functions and report generation for strategy validation."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parent


def diag_overlap(strategies, splits):
    """1. Strategy overlap — % of bets on same game_id+player_id."""
    print("\n" + "=" * 60)
    print("  1. STRATEGY OVERLAP MATRIX")
    print("=" * 60)

    strat_keys = {}
    for sname, split_data in strategies.items():
        keys = set()
        for label, df in split_data.items():
            for _, r in df.iterrows():
                keys.add((r['game_id'], r['player_id']))
        strat_keys[sname] = keys

    names = list(strat_keys.keys())

    print(f"\n{'':40s}", end='')
    for name in names:
        print(f"{name[:8]:>10s}", end='')
    print()

    overlap_data = []
    for i, a in enumerate(names):
        print(f"{a:40s}", end='')
        for j, b in enumerate(names):
            if not strat_keys[a] or not strat_keys[b]:
                pct = 0
            elif a == b:
                pct = 100
            else:
                overlap = len(strat_keys[a] & strat_keys[b])
                pct = overlap / min(len(strat_keys[a]), len(strat_keys[b])) * 100
            print(f"{pct:9.0f}%", end='')
            if i != j:
                overlap_data.append((a, b, pct))
        print()

    high = [(a, b, p) for a, b, p in overlap_data if p > 70]
    if high:
        print("\n⚠️ High overlap (>70%):")
        for a, b, p in high:
            print(f"  {a} ↔ {b}: {p:.0f}%")
    else:
        print("\n✅ No pair has >70% overlap — strategies are reasonably independent")

    return overlap_data


def diag_fold_stability(strategies, splits):
    """2. ROI by individual season/fold."""
    print("\n" + "=" * 60)
    print("  2. FOLD-LEVEL STABILITY")
    print("=" * 60)

    split_labels = [s['label'] for s in splits]
    header = f"{'Strategy':40s}"
    for sl in split_labels:
        header += f"{'  ' + sl + ' ROI':>12s}{'  ' + sl + ' Bets':>10s}"
    header += f"{'  Avg ROI':>10s}{'  Flag':>8s}"
    print(f"\n{header}")
    print("-" * len(header))

    results = []
    for sname, split_data in strategies.items():
        row = f"{sname:40s}"
        rois = []
        flagged = False
        for sl in split_labels:
            if sl in split_data and len(split_data[sl]) > 0:
                df = split_data[sl]
                n_bets = len(df)
                roi = (df['profit'].sum() / n_bets) * 100
                rois.append(roi)
                row += f"{roi:+10.1f}%  {n_bets:8d}"
                if roi < 5:
                    flagged = True
            else:
                row += f"{'N/A':>12s}{'0':>10s}"
                rois.append(None)

        avg_roi = np.mean([r for r in rois if r is not None]) if rois else 0
        flag = "⚠️" if flagged else "✅"
        row += f"{avg_roi:+8.1f}%  {flag}"
        print(row)
        results.append({'strategy': sname, 'rois': rois, 'flagged': flagged})

    return results


def diag_clv_proxy(strategies, splits):
    """3. Closing Line Value proxy — line movement analysis."""
    print("\n" + "=" * 60)
    print("  3. CLV PROXY (Line Movement Analysis)")
    print("=" * 60)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        avg_movement = all_bets['line_movement'].mean()
        side = all_bets['side'].iloc[0]

        if side == 'under':
            clv_aligned = (all_bets['line_movement'] < 0).mean() * 100
        else:
            clv_aligned = (all_bets['line_movement'] > 0).mean() * 100

        if side == 'under':
            all_bets['line_favor'] = all_bets['line_movement'] < 0
        else:
            all_bets['line_favor'] = all_bets['line_movement'] > 0

        favor_wr = all_bets[all_bets['line_favor']]['won'].mean() * 100 if all_bets['line_favor'].sum() > 5 else 0
        against_wr = all_bets[~all_bets['line_favor']]['won'].mean() * 100 if (~all_bets['line_favor']).sum() > 5 else 0

        print(f"\n  {sname} ({side.upper()}):")
        print(f"    Avg line movement on our bets: {avg_movement:+.2f} saves")
        print(f"    % bets where line moved in our direction: {clv_aligned:.0f}%")
        print(f"    Win rate when line moved in our favor: {favor_wr:.0f}%")
        print(f"    Win rate when line moved against us: {against_wr:.0f}%")


def diag_juice_sensitivity(strategies, splits):
    """4. Juice sensitivity — ROI at different vig levels."""
    print("\n" + "=" * 60)
    print("  4. JUICE SENSITIVITY")
    print("=" * 60)

    juice_levels = {
        '-105 (sharp)': -105, '-110 (standard)': -110,
        '-115 (bad book)': -115, '-120 (terrible)': -120,
    }

    print("\n  Breakeven win rates:")
    for label, juice in juice_levels.items():
        be = (-juice) / (-juice + 100) * 100
        print(f"    {label}: {be:.1f}%")

    print(f"\n  {'Strategy':40s}{'Win%':>8s}{'@-105':>10s}{'@-110':>10s}{'@-115':>10s}{'@-120':>10s}{'Margin':>10s}")
    print("  " + "-" * 108)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        actual_wr = all_bets['won'].mean() * 100
        n = len(all_bets)

        rois = {}
        for label, juice in juice_levels.items():
            payout = 100 / (-juice)
            profit = all_bets['won'].sum() * payout - (~all_bets['won'] & ~all_bets['push']).sum()
            roi = (profit / n) * 100
            rois[label] = roi

        be_110 = 110 / 210 * 100
        margin = actual_wr - be_110

        row = f"  {sname:40s}{actual_wr:7.1f}%"
        for label in juice_levels:
            r = rois[label]
            emoji = "🟢" if r > 0 else "🔴"
            row += f"  {emoji}{r:+6.1f}%"
        row += f"  {margin:+7.1f}pp"
        print(row)


def diag_confidence_intervals(strategies, splits):
    """5. 95% CI on win rate."""
    print("\n" + "=" * 60)
    print("  5. SAMPLE SIZE CONFIDENCE INTERVALS (95%)")
    print("=" * 60)

    be_110 = 110 / 210

    print(f"\n  {'Strategy':40s}{'Win%':>8s}{'CI Low':>10s}{'CI High':>10s}{'Bets':>8s}{'vs BE':>10s}")
    print("  " + "-" * 86)

    for sname, split_data in strategies.items():
        all_bets = pd.concat(split_data.values(), ignore_index=True) if split_data else pd.DataFrame()
        if len(all_bets) == 0:
            continue

        n = len(all_bets)
        wins = all_bets['won'].sum()
        p = wins / n

        z = 1.96
        denom = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denom
        spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
        ci_low = max(0, center - spread)
        ci_high = min(1, center + spread)

        safe = "✅ SAFE" if ci_low > be_110 else "⚠️ CAUTION"
        print(f"  {sname:40s}{p*100:7.1f}%{ci_low*100:9.1f}%{ci_high*100:9.1f}%{n:8d}  {safe}")


def write_report(overlap_data, fold_results, strategies, splits):
    """Write validation_diagnostics.md."""
    lines = [f"# Validation Diagnostics — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    lines.append("## 1. Strategy Overlap")
    high_overlaps = [(a, b, p) for a, b, p in overlap_data if p > 70]
    if high_overlaps:
        lines.append(f"⚠️ {len(high_overlaps)} pairs have >70% overlap — not fully independent edges.")
        for a, b, p in high_overlaps:
            lines.append(f"- {a} ↔ {b}: {p:.0f}% overlap")
    else:
        lines.append("✅ No pair exceeds 70% overlap — strategies fire on different games and provide independent signals.")
    lines.append("")

    lines.append("## 2. Fold Stability")
    for r in fold_results:
        flag = "⚠️" if r['flagged'] else "✅"
        rois_str = " | ".join([f"{x:+.1f}%" if x is not None else "N/A" for x in r['rois']])
        lines.append(f"- {flag} **{r['strategy']}**: {rois_str}")
    flagged = [r for r in fold_results if r['flagged']]
    if flagged:
        lines.append(f"\n{len(flagged)} strategies have a weak season (<5% ROI) — signals may be inconsistent in certain market regimes.")
    else:
        lines.append("\nAll strategies profitable every season — strong temporal consistency.")
    lines.append("")

    lines.append("## 3. CLV Proxy")
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            avg_mv = ab['line_movement'].mean()
            side = ab['side'].iloc[0]
            aligned = "favorable" if (side == 'under' and avg_mv < 0) or (side == 'over' and avg_mv > 0) else "neutral/unfavorable"
            lines.append(f"- **{sname}**: Avg line movement {avg_mv:+.2f}, direction {aligned} for our {side} bets.")
    lines.append("")

    lines.append("## 4. Juice Sensitivity")
    be_105 = 105 / 205 * 100
    be_110 = 110 / 210 * 100
    be_115 = 115 / 215 * 100
    lines.append(f"Breakeven: -105 → {be_105:.1f}%, -110 → {be_110:.1f}%, -115 → {be_115:.1f}%\n")
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            wr = ab['won'].mean() * 100
            survives_115 = "✅ survives -115" if wr > be_115 else "⚠️ breaks at -115"
            lines.append(f"- **{sname}**: {wr:.1f}% win rate — {survives_115}")
    lines.append("")

    lines.append("## 5. Confidence Intervals")
    be = 110 / 210
    for sname, split_data in strategies.items():
        if split_data:
            ab = pd.concat(split_data.values(), ignore_index=True)
            n = len(ab)
            p = ab['won'].mean()
            z = 1.96
            denom = 1 + z**2 / n
            center = (p + z**2 / (2*n)) / denom
            spread = z * np.sqrt((p*(1-p) + z**2/(4*n)) / n) / denom
            ci_low = max(0, center - spread)
            safe = "✅" if ci_low > be else "⚠️"
            lines.append(f"- {safe} **{sname}**: {p*100:.1f}% [{ci_low*100:.1f}%, {min(1,center+spread)*100:.1f}%] on {n} bets")
    lines.append("\nStrategies where CI lower bound falls below 52.4% (breakeven at -110) need larger sample or tighter filters.")
    lines.append("")

    report_path = MODEL_DIR / 'validation_diagnostics.md'
    with open(report_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"\n\nReport saved to {report_path}")

    with open(MODEL_DIR / 'strategy.md', 'a') as f:
        f.write(f"\n## Validation Diagnostics — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("See validation_diagnostics.md for full report.\n")
        safe_count = sum(1 for r in fold_results if not r['flagged'])
        f.write(f"- {safe_count}/{len(fold_results)} strategies pass all stability checks\n")
        if high_overlaps:
            f.write(f"- ⚠️ {len(high_overlaps)} high-overlap pairs detected\n")
        else:
            f.write("- ✅ All strategy pairs have <70% overlap\n")
    return report_path
