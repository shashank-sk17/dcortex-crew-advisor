import {
  ChangeDetectionStrategy, Component, Input, computed, signal,
} from '@angular/core';
import { CrewLite, DownstreamLeg, FlightDetail } from '../../core/api.types';

interface Leg {
  no: string;
  from: string;
  to: string;
  x1: number;
  x2: number;
  kind: 'break' | 'orphan' | 'knock' | 'ok';
  delay: number;
  label: string;
}
interface Node { x: number; code: string; }

const VW = 1000;
const PAD = 46;

/**
 * The disruption plotted on the network: the broken leg in breach ink, its
 * downstream shockwave hatched, the aircraft knock-on in reference ink.
 * Absorbs the blast radius; the one before -> after redraw lives here.
 */
@Component({
  selector: 'app-route-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './route-chart.component.html',
  styleUrl: './route-chart.component.scss',
})
export class RouteChartComponent {
  readonly vw = VW;
  private readonly _flight = signal<FlightDetail | null>(null);
  private readonly _down = signal<DownstreamLeg[]>([]);
  @Input() crew: CrewLite | null = null;
  @Input() applied = false; // false = baseline, true = after the disruption (drives the redraw)

  @Input() set flight(f: FlightDetail | null) { this._flight.set(f); }
  @Input() set downstream(d: DownstreamLeg[]) { this._down.set(d ?? []); }

  private readonly all = computed(() => {
    const f = this._flight();
    if (!f) return null;
    const raw = [
      { no: f.flight_no, from: f.dep_station, to: f.arr_station, dep: Date.parse(f.dep_utc), arr: Date.parse(f.arr_utc), same: true, delay: 0, break: true },
      ...this._down().map((l) => ({
        no: l.flight_no, from: l.dep_station, to: l.arr_station,
        dep: Date.parse(l.dep_utc), arr: Date.parse(l.arr_utc),
        same: l.same_pairing, delay: l.cumulative_delay_min, break: false,
      })),
    ];
    const t0 = Math.min(...raw.map((r) => r.dep));
    const t1 = Math.max(...raw.map((r) => r.arr));
    const span = Math.max(1, t1 - t0);
    const x = (t: number) => PAD + ((t - t0) / span) * (VW - PAD * 2);
    return { raw, x };
  });

  readonly legs = computed<Leg[]>(() => {
    const a = this.all();
    if (!a) return [];
    return a.raw.map((r) => ({
      no: r.no, from: r.from, to: r.to,
      x1: a.x(r.dep), x2: a.x(r.arr),
      kind: r.break ? 'break' : r.same ? 'orphan' : 'knock',
      delay: r.delay,
      label: r.break ? 'uncovered' : r.same ? 'orphaned' : 'aircraft',
    }));
  });

  readonly nodes = computed<Node[]>(() => {
    const a = this.all();
    if (!a) return [];
    const out: Node[] = [];
    const seen = new Set<string>();
    for (const r of a.raw) {
      const k1 = r.from + '@' + Math.round(a.x(r.dep));
      if (!seen.has(k1)) { out.push({ x: a.x(r.dep), code: r.from }); seen.add(k1); }
      const k2 = r.to + '@' + Math.round(a.x(r.arr));
      if (!seen.has(k2)) { out.push({ x: a.x(r.arr), code: r.to }); seen.add(k2); }
    }
    return out;
  });

  readonly maxDelay = computed(() => Math.max(0, ...this.legs().map((l) => l.delay)));
  readonly orphanCount = computed(() => this.legs().filter((l) => l.kind === 'orphan').length);
  readonly pax = computed(() => this._flight()?.pax_estimate ?? 0);
  readonly tail = computed(() => this._flight()?.aircraft ?? '—');
  readonly axisY = 74;
}
