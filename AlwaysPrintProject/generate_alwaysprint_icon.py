#!/usr/bin/env python3
"""
Generate the current AlwaysPrint icon SVG.

The icon is assembled as a layered vector model:
1. rear paper/input tray
2. printer body with shading
3. lower output opening
4. infinite ribbon loop
5. metallic output paper

The infinity loop itself is generated mathematically as a Bernoulli lemniscate.
The two very small bevel cues at the crossing are kept as hand-tuned paths because
their position was visually adjusted pixel-by-pixel in the final version.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def bernoulli_lemniscate_path(
    cx: float = 512.0,
    cy: float = 480.0,
    a: float = 288.0,
    y_scale: float = 1.24,
    samples: int = 3600,
) -> str:
    """Return the closed SVG path for the infinity loop centerline."""
    points: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = 2.0 * math.pi * i / samples
        s = math.sin(t)
        c = math.cos(t)
        d = 1.0 + s * s
        x = a * c / d
        y = y_scale * a * s * c / d
        points.append((cx + x, cy - y))

    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"


# These two tiny cues were tuned manually after the mathematical construction:
# - the upper illuminated cue indicates that the NW→SE ribbon passes over the crossing
# - the lower shaded cue reinforces the same overpass on the lower edge
UPPER_ILLUMINATED_SEGMENT = """M 491.09 397.13 L 491.19 397.24 L 491.48 397.57 L 491.79 397.91 L 492.08 398.24 L 492.39 398.58 L 492.69 398.91 L 492.99 399.25 L 493.29 399.59 L 493.59 399.93 L 493.89 400.26 L 494.18 400.60 L 494.48 400.93 L 494.79 401.28 L 495.08 401.61 L 495.38 401.95 L 495.67 402.28 L 495.97 402.63 L 496.27 402.96 L 496.56 403.30 L 496.86 403.64 L 497.15 403.98 L 497.45 404.31 L 497.74 404.65 L 498.03 404.99 L 498.33 405.33 L 498.61 405.66 L 498.91 406.01 L 499.21 406.34 L 499.49 406.69 L 499.79 407.02 L 500.07 407.36 L 500.37 407.70 L 500.66 408.04 L 500.95 408.37 L 501.24 408.72 L 501.52 409.05 L 501.82 409.40 L 502.11 409.73 L 502.39 410.07 L 502.68 410.41 L 502.97 410.75 L 503.26 411.09 L 503.55 411.43 L 503.83 411.77 L 504.12 412.11 L 504.40 412.44 L 504.69 412.79 L 504.97 413.12 L 505.26 413.47 L 505.54 413.80 L 505.82 414.15 L 506.11 414.48 L 506.39 414.83 L 506.68 415.16 L 506.96 415.50 L 507.24 415.84 L 507.53 416.18 L 507.80 416.52 L 508.09 416.86 L 508.37 417.20 L 508.65 417.54 L 508.93 417.87 L 509.21 418.22 L 509.49 418.55 L 509.78 418.90 L 510.05 419.23 L 510.33 419.58 L 510.61 419.91 L 510.89 420.25 L 511.17 420.59 L 511.44 420.93 L 511.73 421.27 L 512.00 421.61 L 512.28 421.95 L 512.56 422.29 L 512.83 422.63 L 513.11 422.97 L 513.38 423.31 L 513.66 423.64 L 513.94 423.99 L 514.21 424.32 L 514.49 424.66 L 514.76 425.00 L 515.04 425.34 L 515.32 425.67 L 515.58 426.02 L 515.86 426.35 L 516.13 426.69 L 516.41 427.03 L 516.69 427.37 L 516.95 427.70 L 517.23 428.04 L 517.50 428.39 L 517.77 428.72 L 518.04 429.06 L 518.31 429.39 L 518.59 429.74 L 518.85 430.07 L 519.13 430.41 L 519.39 430.74 L 519.67 431.08 L 519.94 431.41 L 520.21 431.76 L 520.48 432.09 L 520.74 432.43 L 521.02 432.76 L 521.29 433.10 L 521.55 433.44 L 521.83 433.77 L 522.09 434.11 L 522.36 434.44 L 522.63 434.78 L 522.90 435.11 L 523.17 435.45 L 523.43 435.78 L 523.70 436.12 L 523.96 436.45 L 524.23 436.79 L 524.50 437.12 L 524.76 437.46 L 525.03 437.80 L 525.29 438.13 L 525.56 438.47 L 525.83 438.80 L 526.09 439.14 L 526.36 439.46 L 526.62 439.80 L 526.89 440.13 L 527.16 440.47 L 527.42 440.80 L 527.69 441.13 L 527.95 441.46 L 528.21 441.80 L 528.47 442.14 L 528.74 442.46 L 529.01 442.80 L 529.27 443.12 L 529.53 443.46 L 529.79 443.79 L 530.06 444.12 L 530.32 444.45 L 530.58 444.78 L 530.85 445.11 L 531.10 445.44 L 531.37 445.78 L 531.63 446.10 L 531.89 446.44 L 532.16 446.76 L 532.41 447.10 L 532.68 447.42 L 532.93 447.75 L 533.20 448.08 L 533.46 448.41 L 533.72 448.74 L 533.98 449.07 L 534.24 449.40 L 534.50 449.72 L 534.76 450.05 L 535.02 450.37 L 535.29 450.71 L 535.54 451.03 L 535.80 451.36 L 536.06 451.68 L 536.32 452.01 L 536.57 452.34 L 536.84 452.66 L 537.10 452.99 L 537.35 453.31 L 537.62 453.64 L 537.87 453.96 L 538.13 454.29 L 538.38 454.60 L 538.65 454.93 L 538.91 455.26 L 539.16 455.58 L 539.42 455.91 L 539.68 456.22 L 539.94 456.55 L 540.19 456.87 L 540.45 457.19 L 540.71 457.51 L 540.96 457.83 L 541.23 458.16 L 541.48 458.48 L 541.74 458.80 L 541.99 459.11 L 542.25 459.44 L 542.50 459.75 L 542.76 460.08 L 543.02 460.39 L 543.28 460.71 L 543.54 461.04 L 543.79 461.35 L 544.05 461.67 L 544.30 461.98 L 544.56 462.31 L 544.81 462.62 L 545.07 462.94 L 545.33 463.25 L 545.58 463.57 L 545.84 463.89 L 546.09 464.20 L 546.35 464.52 L 546.60 464.83 L 546.86 465.15 L 547.11 465.46 L 547.37 465.77 L 547.63 466.09 L 547.88 466.40 L 548.14 466.72 L 548.39 467.02 L 548.65 467.34 L 548.90 467.64 L 549.16 467.96 L 549.41 468.27 L 549.66 468.58 L 549.92 468.90 L 550.17 469.20 L 550.43 469.51 L 550.68 469.82 L 550.94 470.13 L 551.19 470.43 L 551.45 470.75 L 551.70 471.05 L 551.96 471.36 L 552.21 471.67 L 552.46 471.97 L 552.71 472.28 L 552.97 472.58 L 553.23 472.89 L 553.48 473.19 L 553.74 473.50 L 553.99 473.81 L 554.25 474.11 L 554.49 474.42 L 554.75 474.72 L 555.00 475.02 L 555.26 475.32 L 555.51 475.63 L 555.77 475.92 L 556.02 476.23 L 556.28 476.53 L 556.52 476.83 L 556.78 477.13 L 557.04 477.43 L 557.29 477.73 L 557.34 477.79 L 573.67 496.72"""
LOWER_SHADED_SEGMENT = """M 445.43 461.13 L 445.50 461.21 L 445.75 461.51 L 446.00 461.80 L 446.26 462.10 L 446.51 462.40 L 446.76 462.69 L 447.01 462.99 L 447.27 463.29 L 447.52 463.59 L 447.77 463.88 L 448.02 464.18 L 448.27 464.48 L 448.53 464.78 L 448.78 465.08 L 449.03 465.38 L 449.28 465.68 L 449.53 465.97 L 449.78 466.27 L 450.04 466.57 L 450.29 466.87 L 450.54 467.17 L 450.79 467.47 L 451.04 467.77 L 451.29 468.07 L 451.54 468.37 L 451.79 468.68 L 452.05 468.98 L 452.30 469.28 L 452.55 469.58 L 452.80 469.88 L 453.05 470.18 L 453.30 470.48 L 453.55 470.79 L 453.80 471.09 L 454.05 471.39 L 454.30 471.69 L 454.55 471.99 L 454.80 472.30 L 455.05 472.60 L 455.30 472.90 L 455.55 473.21 L 455.80 473.51 L 456.05 473.81 L 456.30 474.12 L 456.56 474.42 L 456.81 474.73 L 457.06 475.03 L 457.31 475.33 L 457.56 475.64 L 457.81 475.94 L 458.06 476.25 L 458.31 476.55 L 458.56 476.86 L 458.81 477.16 L 459.06 477.47 L 459.31 477.77 L 459.56 478.08 L 459.80 478.38 L 460.05 478.69 L 460.30 479.00 L 460.55 479.30 L 460.80 479.61 L 461.05 479.91 L 461.30 480.22 L 461.55 480.53 L 461.80 480.83 L 462.05 481.14 L 462.30 481.45 L 462.55 481.76 L 462.80 482.06 L 463.05 482.37 L 463.30 482.68 L 463.55 482.98 L 463.80 483.29 L 464.05 483.60 L 464.30 483.91 L 464.55 484.22 L 464.80 484.52 L 465.05 484.83 L 465.30 485.14 L 465.55 485.45 L 465.80 485.76 L 466.05 486.07 L 466.30 486.38 L 466.55 486.69 L 466.80 486.99 L 467.05 487.30 L 467.30 487.61 L 467.55 487.92 L 467.80 488.23 L 468.05 488.54 L 468.30 488.85 L 468.55 489.16 L 468.80 489.47 L 469.05 489.78 L 469.30 490.09 L 469.55 490.40 L 469.81 490.71 L 470.06 491.02 L 470.31 491.33 L 470.56 491.64 L 470.81 491.95 L 471.06 492.26 L 471.31 492.58 L 471.56 492.89 L 471.81 493.20 L 472.06 493.51 L 472.31 493.82 L 472.56 494.13 L 472.82 494.44 L 473.07 494.75 L 473.32 495.07 L 473.57 495.38 L 473.82 495.69 L 474.07 496.00 L 474.32 496.31 L 474.58 496.63 L 474.83 496.94 L 475.08 497.25 L 475.33 497.56 L 475.58 497.87 L 475.83 498.19 L 476.09 498.50 L 476.34 498.81 L 476.59 499.12 L 476.84 499.44 L 477.10 499.75 L 477.35 500.06 L 477.60 500.37 L 477.85 500.69 L 478.11 501.00 L 478.36 501.31 L 478.61 501.63 L 478.87 501.94 L 479.12 502.25 L 479.37 502.57 L 479.63 502.88 L 479.88 503.19 L 480.13 503.51 L 480.39 503.82 L 480.64 504.13 L 480.89 504.45 L 481.15 504.76 L 481.40 505.07 L 481.66 505.39 L 481.91 505.70 L 482.17 506.02 L 482.42 506.33 L 482.68 506.64 L 482.93 506.96 L 483.19 507.27 L 483.44 507.59 L 483.70 507.90 L 483.95 508.22 L 484.21 508.53 L 484.46 508.84 L 484.72 509.16 L 484.97 509.47 L 485.23 509.79 L 485.49 510.10 L 485.74 510.42 L 486.00 510.73 L 486.26 511.05 L 486.51 511.36 L 486.77 511.67 L 487.03 511.99 L 487.28 512.30 L 487.54 512.62 L 487.80 512.93 L 488.06 513.25 L 488.31 513.56 L 488.57 513.88 L 488.83 514.19 L 489.09 514.51 L 489.35 514.82 L 489.61 515.14 L 489.87 515.45 L 490.12 515.77 L 490.38 516.08 L 490.64 516.40 L 490.90 516.71 L 491.16 517.03 L 491.42 517.34 L 491.68 517.66 L 491.94 517.97 L 492.20 518.29 L 492.46 518.60 L 492.73 518.92 L 492.99 519.23 L 493.25 519.55 L 493.51 519.86 L 493.77 520.18 L 494.03 520.49 L 494.29 520.81 L 494.56 521.12 L 494.82 521.44 L 495.08 521.76 L 495.34 522.07 L 495.61 522.39 L 495.87 522.70 L 496.13 523.02 L 496.40 523.33 L 496.66 523.65 L 496.93 523.96 L 497.19 524.28 L 497.46 524.59 L 497.72 524.91 L 497.98 525.22 L 498.25 525.54 L 498.52 525.85 L 498.78 526.17 L 499.05 526.48 L 499.31 526.80 L 499.58 527.11 L 499.85 527.43 L 500.11 527.74 L 500.38 528.06 L 500.65 528.37 L 500.91 528.69 L 501.18 529.00 L 501.45 529.32 L 501.72 529.63 L 501.99 529.95 L 502.26 530.26 L 502.53 530.58 L 502.79 530.89 L 503.06 531.21 L 503.33 531.52 L 503.60 531.83 L 503.87 532.15 L 504.14 532.46 L 504.42 532.78 L 504.69 533.09 L 504.96 533.41 L 505.23 533.72 L 505.50 534.04 L 505.77 534.35 L 506.05 534.66 L 506.32 534.98 L 506.59 535.29 L 506.87 535.61 L 507.14 535.92 L 507.41 536.23 L 507.69 536.55 L 507.96 536.86 L 508.24 537.18 L 508.51 537.49 L 508.79 537.80 L 509.06 538.12 L 509.34 538.43 L 509.61 538.74 L 509.89 539.06 L 510.17 539.37 L 510.44 539.68 L 510.72 540.00 L 511.00 540.31 L 511.28 540.62 L 511.56 540.94 L 511.83 541.25 L 512.11 541.56 L 512.39 541.87 L 512.67 542.19 L 512.95 542.50 L 513.23 542.81 L 513.51 543.12 L 513.79 543.44 L 514.08 543.75 L 514.36 544.06 L 514.64 544.37 L 514.92 544.68 L 515.20 545.00 L 515.49 545.31 L 515.77 545.62 L 516.05 545.93 L 516.34 546.24 L 516.62 546.55 L 516.91 546.86 L 517.19 547.18 L 517.48 547.49 L 517.76 547.80 L 518.05 548.11 L 518.33 548.42 L 518.62 548.73 L 518.91 549.04 L 519.20 549.35 L 519.48 549.66 L 519.77 549.97 L 520.06 550.28 L 520.35 550.59 L 520.64 550.90 L 520.93 551.21 L 521.22 551.52 L 521.51 551.83 L 521.80 552.14 L 522.09 552.45 L 522.38 552.76 L 522.67 553.07 L 522.97 553.37 L 523.26 553.68 L 523.55 553.99 L 523.85 554.30 L 524.14 554.61 L 524.43 554.92 L 524.73 555.22 L 525.02 555.53 L 525.32 555.84 L 525.61 556.15 L 525.91 556.45 L 526.21 556.76 L 526.50 557.07 L 526.80 557.37 L 527.10 557.68 L 527.40 557.99 L 527.70 558.29 L 528.00 558.60 L 528.30 558.90 L 528.60 559.21 L 528.90 559.52 L 528.91 559.53 L 529.20 559.82 L 529.21 559.84 L 529.50 560.13 L 529.52 560.14 L 529.80 560.43 L 529.82 560.45 L 530.10 560.74 L 530.12 560.75 L 530.41 561.04 L 530.42 561.06 L 530.71 561.35 L 530.73 561.36 L 531.01 561.65 L 531.03 561.67 L 531.32 561.95 L 531.33 561.97 L 531.62 562.26 L 531.64 562.28 L 531.92 562.56 L 531.94 562.58 L 532.23 562.86 L 532.25 562.88 L 532.54 563.17 L 532.55 563.19 L 532.84 563.47 L 532.86 563.49 L 533.15 563.77 L 533.17 563.79 L 533.46 564.08 L 533.47 564.10 L 533.76 564.38 L 533.78 564.40 L 534.07 564.68 L 534.09 564.70 L 534.38 564.98 L 534.40 565.00 L 534.69 565.29 L 534.71 565.30 L 535.00 565.59 L 535.02 565.61 L 535.31 565.89 L 535.33 565.91 L 535.62 566.19 L 535.64 566.21 L 535.93 566.49 L 535.95 566.51 L 536.24 566.79 L 536.26 566.81 L 536.55 567.09 L 536.57 567.11 L 536.86 567.39 L 536.88 567.41 L 537.18 567.69 L 537.20 567.71 L 537.49 567.99 L 537.51 568.01 L 537.80 568.29 L 537.82 568.31 L 538.12 568.59 L 538.14 568.61 L 538.43 568.89 L 538.45 568.91 L 538.75 569.19 L 538.77 569.21 L 539.06 569.49 L 539.08 569.51 L 539.38 569.79 L 539.40 569.81 L 539.70 570.08 L 539.72 570.10 L 540.01 570.38 L 540.03 570.40 L 540.33 570.68 L 540.35 570.70 L 540.65 570.98 L 540.67 571.00 L 540.97 571.27 L 540.99 571.29 L 541.29 571.57 L 541.31 571.59 L 541.61 571.87 L 541.63 571.89 L 541.93 572.16 L 541.95 572.18 L 542.25 572.46 L 542.27 572.48 L 542.57 572.76 L 542.59 572.78 L 542.89 573.05 L 542.91 573.07 L 543.21 573.35 L 543.24 573.37 L 543.54 573.64 L 543.56 573.66 L 543.86 573.94 L 543.88 573.96 L 544.18 574.23 L 544.21 574.25 L 544.51 574.52 L 544.53 574.54 L 544.83 574.82 L 544.86 574.84 L 545.16 575.11 L 545.18 575.13 L 545.48 575.40 L 545.51 575.43 L 545.81 575.70 L 545.83 575.72 L 546.14 575.99 L 546.16 576.01 L 546.46 576.28 L 546.49 576.30 L 546.79 576.57 L 546.82 576.60 L 547.12 576.87 L 547.14 576.89 L 547.45 577.16 L 547.47 577.18 L 547.78 577.45 L 547.80 577.47 L 548.11 577.74 L 548.13 577.76 L 548.44 578.03 L 548.47 578.05 L 548.77 578.32 L 548.80 578.34 L 549.10 578.61 L 549.13 578.63 L 549.44 578.90 L 549.46 578.92 L 549.77 579.19 L 549.79 579.21 L 550.10 579.48 L 550.13 579.50 L 550.44 579.76 L 550.46 579.79 L 550.77 580.05 L 550.80 580.08 L 551.11 580.34 L 551.13 580.36 L 551.44 580.63 L 551.47 580.65 L 551.78 580.91 L 551.81 580.94 L 552.12 581.20 L 552.14 581.22 L 552.45 581.49 L 552.48 581.51 L 552.79 581.77 L 552.82 581.80 L 553.13 582.06 L 553.16 582.08 L 553.47 582.34 L 553.50 582.37 L 553.81 582.63 L 553.84 582.65 L 554.15 582.91 L 554.18 582.94 L 554.49 583.20 L 554.52 583.22 L 554.83 583.48 L 554.86 583.50 L 555.18 583.77 L 555.20 583.79 L 555.52 584.05 L 555.55 584.07 L 555.86 584.33 L 555.89 584.35 L 556.21 584.61 L 556.23 584.64 L 556.55 584.89 L 556.58 584.92 L 556.90 585.18 L 556.93 585.20 L 557.24 585.46 L 557.27 585.48 L 557.59 585.74 L 557.62 585.76 L 557.94 586.02 L 557.96 586.04 L 558.28 586.30 L 558.31 586.32 L 558.63 586.58 L 558.66 586.60 L 558.98 586.86 L 559.01 586.88 L 559.33 587.13 L 559.36 587.16 L 559.68 587.41 L 559.71 587.44 L 560.03 587.69 L 560.06 587.71 L 560.38 587.97 L 560.41 587.99 L 560.73 588.24 L 560.77 588.27 L 561.09 588.52 L 561.12 588.55 L 561.44 588.80 L 561.47 588.82 L 561.55 588.88"""


SVG_TEMPLATE = r"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="rearGrad" x1="512" y1="76" x2="512" y2="260" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#6A6F7C"/>
      <stop offset="100%" stop-color="#32323C"/>
    </linearGradient>

    <linearGradient id="bodyGrad" x1="116" y1="230" x2="908" y2="790" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#EFF0F6"/>
      <stop offset="100%" stop-color="#E6E6F0"/>
    </linearGradient>

    <linearGradient id="bodyEdgeGrad" x1="512" y1="230" x2="512" y2="790" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#D7DAE2"/>
      <stop offset="72%" stop-color="#A5A5AA"/>
      <stop offset="100%" stop-color="#6B717B"/>
    </linearGradient>

    <linearGradient id="bodyBottomShade" x1="512" y1="650" x2="512" y2="800" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>
      <stop offset="72%" stop-color="#7B828C" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="#3F4650" stop-opacity="0.78"/>
    </linearGradient>

    <linearGradient id="caveGrad" x1="512" y1="704" x2="512" y2="800" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#505762"/>
      <stop offset="24%" stop-color="#242A33"/>
      <stop offset="70%" stop-color="#10141B"/>
      <stop offset="100%" stop-color="#040506"/>
    </linearGradient>

    <linearGradient id="caveTopLip" x1="512" y1="704" x2="512" y2="752" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#AEB4BE" stop-opacity="0.56"/>
      <stop offset="100%" stop-color="#343A44" stop-opacity="0"/>
    </linearGradient>

    <linearGradient id="loopBevel" x1="205" y1="300" x2="825" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A8F0FF"/>
      <stop offset="12%" stop-color="#5CDAFF"/>
      <stop offset="28%" stop-color="#159DFF"/>
      <stop offset="46%" stop-color="#2358F4"/>
      <stop offset="60%" stop-color="#2629D8"/>
      <stop offset="78%" stop-color="#6A38F2"/>
      <stop offset="100%" stop-color="#6F24A8"/>
    </linearGradient>

    <linearGradient id="loopMain" x1="205" y1="315" x2="820" y2="632" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#45D2FF"/>
      <stop offset="18%" stop-color="#1EA8FF"/>
      <stop offset="42%" stop-color="#286BFF"/>
      <stop offset="58%" stop-color="#2D30EE"/>
      <stop offset="76%" stop-color="#6839FF"/>
      <stop offset="93%" stop-color="#A451FF"/>
      <stop offset="100%" stop-color="#B870FF"/>
    </linearGradient>

    <linearGradient id="loopTopLight" x1="250" y1="335" x2="760" y2="440" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.48"/>
      <stop offset="45%" stop-color="#FFFFFF" stop-opacity="0.20"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.30"/>
    </linearGradient>


    <linearGradient id="loopBottomRim" x1="220" y1="330" x2="830" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#2BD5FF" stop-opacity="0.00"/>
      <stop offset="36%" stop-color="#1234D9" stop-opacity="0.18"/>
      <stop offset="66%" stop-color="#3020B8" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="#4D1474" stop-opacity="0.56"/>
    </linearGradient>

    <linearGradient id="loopUpperEdgeLight" x1="235" y1="315" x2="790" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.54"/>
      <stop offset="35%" stop-color="#FFFFFF" stop-opacity="0.20"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.28"/>
    </linearGradient>


    <linearGradient id="loopBlueRim" x1="230" y1="300" x2="770" y2="420" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#9AF0FF" stop-opacity="0.58"/>
      <stop offset="40%" stop-color="#4ACFFF" stop-opacity="0.24"/>
      <stop offset="100%" stop-color="#B789FF" stop-opacity="0.18"/>
    </linearGradient>

    <linearGradient id="loopPurpleDarkRim" x1="260" y1="470" x2="790" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#1643E8" stop-opacity="0.04"/>
      <stop offset="48%" stop-color="#3725C9" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="#4B176C" stop-opacity="0.34"/>
    </linearGradient>


    <linearGradient id="crossCastShadowGrad" x1="455" y1="426" x2="570" y2="552" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#05072A" stop-opacity="0.08"/>
      <stop offset="48%" stop-color="#030416" stop-opacity="0.38"/>
      <stop offset="100%" stop-color="#030416" stop-opacity="0.10"/>
    </linearGradient>

    <linearGradient id="loopEdgeBlueLight" x1="245" y1="330" x2="760" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A7F1FF" stop-opacity="0.62"/>
      <stop offset="45%" stop-color="#65D9FF" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#C090FF" stop-opacity="0.16"/>
    </linearGradient>

    <filter id="crossShadowSoft" x="410" y="380" width="220" height="220" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="5"/>
    </filter>


    <linearGradient id="loopTopEdgeLight" x1="225" y1="305" x2="760" y2="420" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A7F2FF" stop-opacity="0.64"/>
      <stop offset="36%" stop-color="#60DCFF" stop-opacity="0.30"/>
      <stop offset="78%" stop-color="#A78BFF" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="#C092FF" stop-opacity="0.12"/>
    </linearGradient>

    <linearGradient id="loopLowerEdgeShade" x1="250" y1="500" x2="820" y2="680" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0A42D8" stop-opacity="0.10"/>
      <stop offset="48%" stop-color="#1A178F" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="#4C126E" stop-opacity="0.46"/>
    </linearGradient>

    <linearGradient id="loopCastOnPrinter" x1="260" y1="410" x2="780" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.12"/>
      <stop offset="48%" stop-color="#000000" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.21"/>
    </linearGradient>

    <linearGradient id="crossCastShadowGrad" x1="450" y1="425" x2="575" y2="552" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#060629" stop-opacity="0.08"/>
      <stop offset="46%" stop-color="#030314" stop-opacity="0.46"/>
      <stop offset="100%" stop-color="#030314" stop-opacity="0.12"/>
    </linearGradient>

    <filter id="loopProjectionBlur" x="120" y="250" width="820" height="470" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="7"/>
    </filter>

    <filter id="crossShadowSoft" x="395" y="370" width="250" height="250" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="6.4"/>
    </filter>


    <linearGradient id="ribbonOverCastShadow" x1="440" y1="420" x2="585" y2="555" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#100A42" stop-opacity="0.06"/>
      <stop offset="45%" stop-color="#07051F" stop-opacity="0.42"/>
      <stop offset="100%" stop-color="#07051F" stop-opacity="0.18"/>
    </linearGradient>

    <filter id="ribbonCastBlur" x="390" y="370" width="270" height="270" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="7.2"/>
    </filter>

    <radialGradient id="crossCleanShadowGrad" cx="50%" cy="50%" r="72%">
      <stop offset="0%" stop-color="#030416" stop-opacity="0.36"/>
      <stop offset="54%" stop-color="#060726" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#060726" stop-opacity="0"/>
    </radialGradient>

    <filter id="crossCleanBlur" x="390" y="370" width="270" height="270" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="7.0"/>
    </filter>

    <clipPath id="crossClipClean">
      <ellipse cx="512" cy="490" rx="88" ry="88"/>
    </clipPath>


    <linearGradient id="crossRibbonShadowGrad2" x1="440" y1="430" x2="585" y2="555" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0B0C35" stop-opacity="0"/>
      <stop offset="38%" stop-color="#080920" stop-opacity="0.34"/>
      <stop offset="72%" stop-color="#080920" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#0B0C35" stop-opacity="0"/>
    </linearGradient>

    <filter id="crossRibbonShadowBlur2" x="400" y="385" width="250" height="230" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="4.8"/>
    </filter>

    <clipPath id="crossClipWide">
      <path d="M 410 390 L 620 390 L 620 610 L 410 610 Z"/>
    </clipPath>


    <linearGradient id="loopBevelRefined" x1="205" y1="300" x2="825" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#9EF0FF"/>
      <stop offset="13%" stop-color="#59DCFF"/>
      <stop offset="30%" stop-color="#149DFF"/>
      <stop offset="48%" stop-color="#2558F5"/>
      <stop offset="62%" stop-color="#2729DA"/>
      <stop offset="78%" stop-color="#6A39F2"/>
      <stop offset="100%" stop-color="#6F25A8"/>
    </linearGradient>

    <linearGradient id="loopMainRefined" x1="205" y1="315" x2="820" y2="632" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#43D3FF"/>
      <stop offset="18%" stop-color="#1CA8FF"/>
      <stop offset="42%" stop-color="#286CFF"/>
      <stop offset="58%" stop-color="#2C31F0"/>
      <stop offset="77%" stop-color="#6A39FF"/>
      <stop offset="94%" stop-color="#A652FF"/>
      <stop offset="100%" stop-color="#BA72FF"/>
    </linearGradient>

    <linearGradient id="loopLowerShadeRefined" x1="250" y1="490" x2="820" y2="680" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0A43D8" stop-opacity="0.08"/>
      <stop offset="48%" stop-color="#1A178F" stop-opacity="0.24"/>
      <stop offset="100%" stop-color="#4C126E" stop-opacity="0.46"/>
    </linearGradient>

    <linearGradient id="loopUpperLightRefined" x1="225" y1="305" x2="760" y2="420" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A9F4FF" stop-opacity="0.58"/>
      <stop offset="42%" stop-color="#68E1FF" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#C18FFF" stop-opacity="0.16"/>
    </linearGradient>

    <linearGradient id="loopCastPrinterRefined" x1="260" y1="410" x2="780" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.10"/>
      <stop offset="48%" stop-color="#000000" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.18"/>
    </linearGradient>

    <linearGradient id="crossBandShadowRefined" x1="442" y1="420" x2="582" y2="560" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#07072A" stop-opacity="0"/>
      <stop offset="35%" stop-color="#05051D" stop-opacity="0.36"/>
      <stop offset="70%" stop-color="#05051D" stop-opacity="0.20"/>
      <stop offset="100%" stop-color="#07072A" stop-opacity="0"/>
    </linearGradient>

    <filter id="loopProjectionBlurRefined" x="120" y="250" width="820" height="470" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="6.2"/>
    </filter>

    <filter id="crossBandBlurRefined" x="395" y="380" width="250" height="240" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="4.8"/>
    </filter>

    <clipPath id="crossCenterClipRefined">
      <path d="M 415 386 L 626 386 L 626 612 L 415 612 Z"/>
    </clipPath>


    <linearGradient id="loopBevelStrongClean" x1="205" y1="300" x2="825" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#8FEAFF"/>
      <stop offset="12%" stop-color="#4BD4FF"/>
      <stop offset="28%" stop-color="#0E98FF"/>
      <stop offset="46%" stop-color="#1E57EF"/>
      <stop offset="60%" stop-color="#2427D6"/>
      <stop offset="78%" stop-color="#6936EF"/>
      <stop offset="100%" stop-color="#7A2BC5"/>
    </linearGradient>

    <linearGradient id="loopMainStrongClean" x1="205" y1="315" x2="820" y2="632" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#35CBFF"/>
      <stop offset="18%" stop-color="#149FFF"/>
      <stop offset="42%" stop-color="#236AFF"/>
      <stop offset="58%" stop-color="#282FF0"/>
      <stop offset="77%" stop-color="#6638FF"/>
      <stop offset="94%" stop-color="#A550FF"/>
      <stop offset="100%" stop-color="#B86FFF"/>
    </linearGradient>

    <linearGradient id="loopDarkUndersideClean" x1="250" y1="500" x2="820" y2="680" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#082EA8" stop-opacity="0.16"/>
      <stop offset="48%" stop-color="#17108C" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="#481065" stop-opacity="0.55"/>
    </linearGradient>

    <linearGradient id="loopLightEdgeClean" x1="210" y1="300" x2="760" y2="420" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#B5F4FF" stop-opacity="0.54"/>
      <stop offset="45%" stop-color="#67DEFF" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#C292FF" stop-opacity="0.12"/>
    </linearGradient>

    <linearGradient id="loopCastPrinterClean" x1="260" y1="410" x2="780" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.10"/>
      <stop offset="48%" stop-color="#000000" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.20"/>
    </linearGradient>

    <filter id="loopProjectionBlurClean" x="110" y="240" width="840" height="500" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="6.8"/>
    </filter>

    <filter id="loopReliefClean" x="70" y="175" width="900" height="570" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feDropShadow dx="4.2" dy="6.0" stdDeviation="5.0" flood-color="#120A55" flood-opacity="0.34"/>
      <feDropShadow dx="-2.8" dy="-3.8" stdDeviation="3.0" flood-color="#78E8FF" flood-opacity="0.24"/>
      <feMerge>
        <feMergeNode/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>


    <linearGradient id="loopBevelFinal" x1="205" y1="300" x2="825" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#AEF3FF"/>
      <stop offset="13%" stop-color="#62DFFF"/>
      <stop offset="29%" stop-color="#119CFF"/>
      <stop offset="47%" stop-color="#245CF4"/>
      <stop offset="62%" stop-color="#2529D8"/>
      <stop offset="79%" stop-color="#6937F0"/>
      <stop offset="100%" stop-color="#7428BA"/>
    </linearGradient>

    <linearGradient id="loopMainFinal" x1="205" y1="315" x2="820" y2="632" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#34CCFF"/>
      <stop offset="18%" stop-color="#149EFF"/>
      <stop offset="42%" stop-color="#236CFF"/>
      <stop offset="58%" stop-color="#2830F0"/>
      <stop offset="77%" stop-color="#6638FF"/>
      <stop offset="94%" stop-color="#A550FF"/>
      <stop offset="100%" stop-color="#B76FFF"/>
    </linearGradient>

    <linearGradient id="loopUndersideFinal" x1="250" y1="500" x2="820" y2="680" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#062EAA" stop-opacity="0.18"/>
      <stop offset="48%" stop-color="#15108A" stop-opacity="0.36"/>
      <stop offset="100%" stop-color="#481064" stop-opacity="0.60"/>
    </linearGradient>

    <linearGradient id="loopTopEdgeFinal" x1="205" y1="300" x2="820" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#B8F5FF" stop-opacity="0.70"/>
      <stop offset="25%" stop-color="#61DEFF" stop-opacity="0.34"/>
      <stop offset="65%" stop-color="#7B77FF" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="#C28CFF" stop-opacity="0.12"/>
    </linearGradient>

    <linearGradient id="loopCastPrinterFinal" x1="260" y1="410" x2="780" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.11"/>
      <stop offset="48%" stop-color="#000000" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.20"/>
    </linearGradient>

    <linearGradient id="crossRibbonShadowFinal" x1="436" y1="415" x2="584" y2="565" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#05051E" stop-opacity="0"/>
      <stop offset="34%" stop-color="#040417" stop-opacity="0.38"/>
      <stop offset="68%" stop-color="#040417" stop-opacity="0.24"/>
      <stop offset="100%" stop-color="#05051E" stop-opacity="0"/>
    </linearGradient>

    <filter id="loopProjectionBlurFinal" x="110" y="240" width="840" height="500" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="6.8"/>
    </filter>

    <filter id="loopReliefFinal" x="70" y="175" width="900" height="570" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feDropShadow dx="4.2" dy="6.0" stdDeviation="5.0" flood-color="#120A55" flood-opacity="0.32"/>
      <feDropShadow dx="-2.8" dy="-3.8" stdDeviation="3.0" flood-color="#78E8FF" flood-opacity="0.22"/>
      <feMerge>
        <feMergeNode/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <filter id="crossRibbonBlurFinal" x="390" y="375" width="270" height="260" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="5.4"/>
    </filter>

    <clipPath id="crossShadowClipFinal">
      <path d="M 410 390 L 625 390 L 625 612 L 410 612 Z"/>
    </clipPath>


    <linearGradient id="loopBevelTwoSegAligned" x1="205" y1="300" x2="825" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A7F2FF"/>
      <stop offset="14%" stop-color="#59DBFF"/>
      <stop offset="30%" stop-color="#109CFF"/>
      <stop offset="47%" stop-color="#245CF4"/>
      <stop offset="62%" stop-color="#2529D8"/>
      <stop offset="79%" stop-color="#6937F0"/>
      <stop offset="100%" stop-color="#7428BA"/>
    </linearGradient>

    <linearGradient id="loopMainTwoSegAligned" x1="205" y1="315" x2="820" y2="632" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#34CCFF"/>
      <stop offset="18%" stop-color="#149EFF"/>
      <stop offset="42%" stop-color="#236CFF"/>
      <stop offset="58%" stop-color="#2830F0"/>
      <stop offset="77%" stop-color="#6638FF"/>
      <stop offset="94%" stop-color="#A550FF"/>
      <stop offset="100%" stop-color="#B76FFF"/>
    </linearGradient>

    <linearGradient id="loopUndersideTwoSegAligned" x1="250" y1="500" x2="820" y2="680" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#062EAA" stop-opacity="0.16"/>
      <stop offset="48%" stop-color="#15108A" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="#481064" stop-opacity="0.58"/>
    </linearGradient>

    <linearGradient id="loopCastPrinterTwoSegAligned" x1="260" y1="410" x2="780" y2="650" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.10"/>
      <stop offset="48%" stop-color="#000000" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.20"/>
    </linearGradient>

    <linearGradient id="overUpperBevelSegAligned" x1="491.09" y1="397.13" x2="573.67" y2="496.72" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A9F3FF" stop-opacity="0"/>
      <stop offset="18%" stop-color="#A9F3FF" stop-opacity="0.62"/>
      <stop offset="78%" stop-color="#79E4FF" stop-opacity="0.50"/>
      <stop offset="100%" stop-color="#79E4FF" stop-opacity="0"/>
    </linearGradient>

    <linearGradient id="overLowerShadeSegAligned" x1="445.43" y1="461.13" x2="561.55" y2="588.88" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#1B178F" stop-opacity="0"/>
      <stop offset="12%" stop-color="#1B178F" stop-opacity="0.24"/>
      <stop offset="78%" stop-color="#3E1678" stop-opacity="0.44"/>
      <stop offset="100%" stop-color="#3E1678" stop-opacity="0"/>
    </linearGradient>

    <filter id="loopProjectionBlurTwoSegAligned" x="110" y="240" width="840" height="500" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="6.8"/>
    </filter>

    <filter id="loopReliefTwoSegAligned" x="70" y="175" width="900" height="570" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feDropShadow dx="4.2" dy="6.0" stdDeviation="5.0" flood-color="#120A55" flood-opacity="0.32"/>
      <feDropShadow dx="-2.8" dy="-3.8" stdDeviation="3.0" flood-color="#78E8FF" flood-opacity="0.20"/>
      <feMerge>
        <feMergeNode/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <linearGradient id="paperMetal" x1="345" y1="716" x2="705" y2="960" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#EEF1F6"/>
      <stop offset="12%" stop-color="#C9CED8"/>
      <stop offset="28%" stop-color="#AEB5C0"/>
      <stop offset="44%" stop-color="#F7F8FA"/>
      <stop offset="58%" stop-color="#C3C8D1"/>
      <stop offset="76%" stop-color="#8F97A3"/>
      <stop offset="100%" stop-color="#5C646F"/>
    </linearGradient>

    <linearGradient id="paperEdge" x1="512" y1="724" x2="512" y2="960" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="18%" stop-color="#E3E7EE"/>
      <stop offset="46%" stop-color="#9DA4AF"/>
      <stop offset="76%" stop-color="#68717C"/>
      <stop offset="100%" stop-color="#3E4650"/>
    </linearGradient>

    <linearGradient id="paperGlint" x1="340" y1="735" x2="712" y2="940" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>
      <stop offset="42%" stop-color="#FFFFFF" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>


    <linearGradient id="paperHardTopLip" x1="512" y1="724" x2="512" y2="770" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.78"/>
      <stop offset="38%" stop-color="#E0E4EB" stop-opacity="0.36"/>
      <stop offset="100%" stop-color="#6F7782" stop-opacity="0.12"/>
    </linearGradient>

    <linearGradient id="paperBottomHeavyBevel" x1="512" y1="900" x2="512" y2="958" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#7E8792" stop-opacity="0.20"/>
      <stop offset="45%" stop-color="#515A65" stop-opacity="0.82"/>
      <stop offset="100%" stop-color="#242A31" stop-opacity="0.92"/>
    </linearGradient>

    <linearGradient id="paperLeftMetalSide" x1="330" y1="720" x2="390" y2="950" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#C5CBD4" stop-opacity="0.55"/>
      <stop offset="60%" stop-color="#727B87" stop-opacity="0.68"/>
      <stop offset="100%" stop-color="#3F4751" stop-opacity="0.75"/>
    </linearGradient>

    <linearGradient id="paperRightMetalSide" x1="670" y1="720" x2="720" y2="950" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#A6ADB8" stop-opacity="0.46"/>
      <stop offset="65%" stop-color="#5A636E" stop-opacity="0.70"/>
      <stop offset="100%" stop-color="#2D343D" stop-opacity="0.78"/>
    </linearGradient>

    <linearGradient id="paperSolidGlint" x1="340" y1="735" x2="710" y2="940" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.00"/>
      <stop offset="36%" stop-color="#FFFFFF" stop-opacity="0.42"/>
      <stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.20"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.00"/>
    </linearGradient>

    <filter id="mainShadow" x="-80" y="-80" width="1184" height="1184" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="18" stdDeviation="16" flood-color="#000000" flood-opacity="0.16"/>
    </filter>

    <filter id="loopShadow" x="80" y="190" width="880" height="540" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="9" stdDeviation="8" flood-color="#000000" flood-opacity="0.24"/>
    </filter>

    <filter id="ledGlow" x="770" y="235" width="150" height="150" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="#72FF4B" flood-opacity="0.95"/>
    </filter>

    <filter id="paperShadow" x="220" y="675" width="620" height="350" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="20" stdDeviation="11" flood-color="#000000" flood-opacity="0.36"/>
    </filter>

    <filter id="crossBlur" x="410" y="400" width="210" height="170" filterUnits="userSpaceOnUse">
      <feGaussianBlur stdDeviation="4"/>
    </filter>

    <filter id="loop3DBevel" x="70" y="180" width="900" height="560" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feDropShadow dx="2.2" dy="3.2" stdDeviation="3.5" flood-color="#1A1268" flood-opacity="0.16"/>
      <feDropShadow dx="-2.0" dy="-2.8" stdDeviation="2.4" flood-color="#82E9FF" flood-opacity="0.16"/>
      <feMerge>
        <feMergeNode/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>




    <clipPath id="bodyClip">
      <path d="
    M 194 230
    H 830
    C 874 230 908 264 908 308
    V 712
    C 908 756 874 790 830 790
    H 762
    V 734
    C 762 720 746 704 732 704
    H 292
    C 278 704 262 720 262 734
    V 790
    H 194
    C 150 790 116 756 116 712
    V 308
    C 116 264 150 230 194 230
    Z
    "/>
    </clipPath>

    <clipPath id="paperClip">
      <path d="M 350 724 L 674 724 L 724 916 C 732 938 714 954 689 954 L 335 954 C 310 954 292 938 300 916 Z"/>
    </clipPath>

    <!-- Only the crossing area is clipped, so the over-layer has no visible caps at the loop ends -->
    <clipPath id="crossClip">
      <ellipse cx="512" cy="480" rx="86" ry="106"/>
    </clipPath>
  </defs>

  <g transform="translate(512 512) scale(1.1) translate(-512 -512)" filter="url(#mainShadow)">
    <!-- 1) Rear tray -->
    <rect x="338" y="76" width="348" height="184" rx="42" fill="url(#rearGrad)"/>
    <rect x="356" y="92" width="312" height="14" rx="7" fill="#AAB0BB" opacity="0.55"/>

    <!-- 2) Printer body and bottom cave -->
    <path d="M 262 790
             V 734
             C 262 720 278 704 292 704
             H 732
             C 746 704 762 720 762 734
             V 790
             Z"
          fill="url(#caveGrad)"/>

    <path d="
    M 194 230
    H 830
    C 874 230 908 264 908 308
    V 712
    C 908 756 874 790 830 790
    H 762
    V 734
    C 762 720 746 704 732 704
    H 292
    C 278 704 262 720 262 734
    V 790
    H 194
    C 150 790 116 756 116 712
    V 308
    C 116 264 150 230 194 230
    Z
    " fill="url(#bodyGrad)" stroke="url(#bodyEdgeGrad)" stroke-width="4"/>

    <path d="M 170 248 H 854" stroke="#FFFFFF" stroke-width="14" stroke-linecap="round" opacity="0.30"/>

    <g clip-path="url(#bodyClip)">
      <path d="M 116 664
               C 124 732 168 790 236 790
               H 262
               V 749
               C 262 732 274 714 292 708
               H 116 Z"
            fill="url(#bodyBottomShade)" opacity="0.96"/>

      <path d="M 908 664
               C 900 732 856 790 788 790
               H 762
               V 749
               C 762 732 750 714 732 708
               H 908 Z"
            fill="url(#bodyBottomShade)" opacity="0.96"/>
    </g>

    <path d="M 298 711
             C 326 706 354 704 392 704
             H 632
             C 670 704 698 706 726 711
             L 706 746
             H 318 Z"
          fill="url(#caveTopLip)"/>

    <g filter="url(#ledGlow)">
      <circle cx="836" cy="302" r="24" fill="#5BFF38" stroke="#00AD21" stroke-width="4"/>
      <circle cx="828" cy="294" r="10" fill="#D9FFB8" opacity="0.85"/>
    </g>

    <!-- 4) Infinity loop: continuous ribbon with correctly aligned directional bevel cues -->
    <!-- subtle shadow projected by the whole loop onto the printer body -->
    <path d="__FULL_LOOP__" fill="none" stroke="url(#loopCastPrinterTwoSegAligned)" stroke-width="68" stroke-linecap="round" stroke-linejoin="round"
          transform="translate(10,13)" filter="url(#loopProjectionBlurTwoSegAligned)" opacity="0.78"/>

    <g filter="url(#loopReliefTwoSegAligned)">
      <!-- lower-right thickness / underside -->
      <path d="__FULL_LOOP__" fill="none" stroke="url(#loopUndersideTwoSegAligned)" stroke-width="82" stroke-linecap="round" stroke-linejoin="round"
            transform="translate(3.0,4.2)" opacity="0.82"/>

      <!-- outer bevel -->
      <path d="__FULL_LOOP__" fill="none" stroke="url(#loopBevelTwoSegAligned)" stroke-width="80" stroke-linecap="round" stroke-linejoin="round"/>

      <!-- main continuous ribbon body -->
      <path d="__FULL_LOOP__" fill="none" stroke="url(#loopMainTwoSegAligned)" stroke-width="64" stroke-linecap="round" stroke-linejoin="round"/>

      <!-- two cues aligned to the actual borders of the NO→SE ribbon -->

      <!-- bevel cues placed directly at the NO→SE overpass crossing -->
      <path d="__UPPER_ILLUMINATED_SEGMENT__" fill="none" stroke="url(#overUpperBevelSegAligned)" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="__LOWER_SHADED_SEGMENT__" fill="none" stroke="url(#overLowerShadeSegAligned)" stroke-width="5.8" stroke-linecap="round" stroke-linejoin="round"/>
    </g>

    <!-- 5) Metallic paper sheet with print lines moved upward -->
    <g filter="url(#paperShadow)">
      <path d="M 350 724 L 674 724 L 724 916 C 732 938 714 954 689 954 L 335 954 C 310 954 292 938 300 916 Z" fill="url(#paperMetal)" stroke="url(#paperEdge)" stroke-width="5"/>

      <g clip-path="url(#paperClip)">
        <!-- strong bottom/front bevel -->
        <path d="M 306 902 L 718 902 L 700 952 L 324 952 Z"
              fill="url(#paperBottomHeavyBevel)" opacity="1"/>

        <!-- solid left and right metal side planes -->
        <path d="M 350 724 L 404 724 L 342 954 L 335 954 C 310 954 294 936 300 916 Z"
              fill="url(#paperLeftMetalSide)"/>
        <path d="M 620 724 L 674 724 L 724 916 C 730 936 714 954 689 954 L 680 954 Z"
              fill="url(#paperRightMetalSide)"/>

        <!-- broad metallic body reflection -->
        <path d="M 338 734 C 462 772 560 836 672 938 L 724 938 L 674 724 Z"
              fill="url(#paperSolidGlint)" opacity="0.92"/>

        <!-- top folded/lip reflection, sharper and more metallic -->
        <path d="M 374 728 L 650 728 L 666 764 L 358 764 Z"
              fill="url(#paperHardTopLip)"/>

        <!-- subtle central darker triangular plane to make it solid, not glassy -->
        <path d="M 440 760 L 684 940 L 560 940 L 350 760 Z"
              fill="#6D7580" opacity="0.13"/>

        <!-- bottom rim dark line inside the sheet -->
        <path d="M 316 926 L 708 926 L 696 952 L 328 952 Z"
              fill="#303842" opacity="0.34"/>
      </g>

      <!-- moved upward to avoid printed lines appearing at the bottom edge -->
      <rect x="418" y="790" width="188" height="20" rx="10" fill="#F5F7FB" opacity="0.94"/>
      <rect x="418" y="790" width="188" height="20" rx="10" fill="none" stroke="#6C7480" stroke-width="2.4" opacity="0.95"/>
      <rect x="400" y="848" width="224" height="20" rx="10" fill="#F5F7FB" opacity="0.94"/>
      <rect x="400" y="848" width="224" height="20" rx="10" fill="none" stroke="#6C7480" stroke-width="2.4" opacity="0.95"/>

      <path d="M 320 944
               C 326 950, 334 952, 346 952
               L 678 952
               C 690 952, 698 950, 704 944"
            fill="none" stroke="#2F3740" stroke-width="9" stroke-linecap="round" opacity="0.72"/>
    </g>
  </g>
</svg>
"""


def build_svg() -> str:
    """Build the SVG exactly as in the current approved version."""
    return (
        SVG_TEMPLATE
        .replace("__FULL_LOOP__", bernoulli_lemniscate_path())
        .replace("__UPPER_ILLUMINATED_SEGMENT__", UPPER_ILLUMINATED_SEGMENT)
        .replace("__LOWER_SHADED_SEGMENT__", LOWER_SHADED_SEGMENT)
    )


def write_svg(output_path: Path) -> Path:
    svg = build_svg()
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def write_png_preview(svg_path: Path, png_path: Path) -> Path:
    """Render an optional PNG preview if CairoSVG is available."""
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError(
            "PNG preview requested, but CairoSVG is not installed. "
            "Install it with: pip install cairosvg"
        ) from exc

    cairosvg.svg2png(
        bytestring=svg_path.read_bytes(),
        write_to=str(png_path),
        output_width=1024,
        output_height=1024,
    )
    return png_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the AlwaysPrint SVG icon.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("alwaysprint_icon.svg"),
        help="Output SVG path. Default: alwaysprint_icon.svg",
    )
    parser.add_argument(
        "--preview-png",
        type=Path,
        default=None,
        help="Optional PNG preview path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    svg_path = write_svg(args.output)
    print(f"SVG written to: {svg_path}")

    if args.preview_png is not None:
        png_path = write_png_preview(svg_path, args.preview_png)
        print(f"PNG preview written to: {png_path}")


if __name__ == "__main__":
    main()
