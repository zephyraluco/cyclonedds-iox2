#!/usr/bin/env python3
"""Create tables and a scientific comparison plot from retained trial data."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plot', action='store_true', help='requires matplotlib')
    args = p.parse_args()
    raw = [json.loads(line) for line in (args.results/'raw.jsonl').read_text().splitlines()]
    if not raw or (args.results/'failure.txt').exists():
        raise RuntimeError('empty or failed run cannot produce a performance report')
    rows = json.loads((args.results/'summary.json').read_text())
    metadata = json.loads((args.results/'metadata.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    same = {(r['language'],r['size_bytes'],r['window'],r['mode']):r
            for r in rows if r['language']==r['server_language']}
    lines = ['# 逐组测量结果', '',
             '数值为各独立进程对试验的中位数；范围是试验最小值–最大值，不是置信区间。', '',
             '| 语言 | 消息 B | 窗口 | 模式 | 重复 | p50 RTT μs（范围） | p99 RTT μs | 有效 MiB/s（范围） | lo TX B |',
             '|---|---:|---:|---|---:|---|---:|---|---:|']
    for key, r in sorted(same.items()):
        lines.append(f"| {r['language']} | {r['size_bytes']} | {r['window']} | {r['mode']} | {r['repeats']} | "
            f"{r['p50_rtt_us']:.2f} ({r['p50_rtt_us_min']:.2f}–{r['p50_rtt_us_max']:.2f}) | "
            f"{r['p99_rtt_us']:.2f} | {r['payload_mib_per_s']:.2f} "
            f"({r['payload_mib_per_s_min']:.2f}–{r['payload_mib_per_s_max']:.2f}) | {r['loopback_tx_bytes']:.0f} |")
    (args.output/'tables.md').write_text('\n'.join(lines)+'\n')
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2,3,figsize=(13,7.5),constrained_layout=True)
        sizes = [64,4096,65536]
        colors = {'udp':'#536878','iox2-copy':'#2674b8','iox2-loan':'#dc6c28'}
        for col, lang in enumerate(['c','cpp','rust']):
            for row, (window, metric, ylabel) in enumerate([
                (1,'p50_rtt_us','RTT p50 (us), window=1'),
                (16,'payload_mib_per_s','Effective MiB/s, window=16')]):
                ax=axes[row,col]
                for mode, color in colors.items():
                    values=[same[lang,s,window,mode] for s in sizes]
                    y=[r[metric] for r in values]
                    bounds=[[r[metric]-r[metric+'_min'] for r in values],
                            [r[metric+'_max']-r[metric] for r in values]]
                    ax.errorbar(range(3),y,yerr=bounds,label=mode,color=color,marker='o',capsize=3)
                ax.set_xticks(range(3),['64 B','4 KiB','64 KiB'])
                ax.set_title({'c':'C','cpp':'C++','rust':'Rust (official sys binding)'}[lang])
                ax.set_ylabel(ylabel);ax.grid(alpha=.25)
                if row==1:ax.set_yscale('log')
        axes[0,0].legend(fontsize=8)
        params = metadata['parameters']
        fig.suptitle('UDP vs iceoryx2: independent trial medians and min/max ranges\n'
                     f"{params['samples']} measured + {params['warmup']} warmup samples; "
                     f"{params['repeats']} trials; shared cloud host")
        fig.savefig(args.output/'comparison.png',dpi=180)
        fig.savefig(args.output/'comparison.svg')
        plt.close(fig)


if __name__=='__main__':
    main()
