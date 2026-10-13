import type { GraphView, TaskId } from '../api/contracts';

export type NodeRole = 'wallet' | 'contract' | 'token' | 'pool' | 'deployer' | 'lp' | 'unknown';
export interface DisplayNode {
  id: string; ref: string; role: NodeRole; label: string | null;
  root: boolean; assessed: boolean | null;
}
export interface DisplayEdge {
  id: string; source: string; target: string; relation: string;
  kind: 'observed' | 'structural'; count: number | null;
  amount: string | null; asset: string | null; firstSeen: string | null; lastSeen: string | null;
}
export interface DisplayGraph {
  sampleId: string; taskId: TaskId; nodes: DisplayNode[]; edges: DisplayEdge[];
}
export interface GraphContext {
  sampleId: string; taskId: TaskId;
  modelNodes?: number; modelEdges?: number;
  window?: string; version?: string; sampling?: string; cutoff?: string;
}
export interface PositionedNode extends DisplayNode { x: number; y: number; depth: number; radius: number; delay: number }
export interface PositionedEdge extends DisplayEdge { path: string; x: number; y: number; delay: number }
export interface GraphScene {
  nodes: PositionedNode[]; edges: PositionedEdge[]; width: number; height: number; minX: number; minY: number;
}
export const taskNames: Record<TaskId, string> = {
  phishing: 'Phishing', ponzi: 'Ponzi', honeypot: 'Honeypot', rug_pull: 'Rug Pull',
};
const roles: NodeRole[] = ['wallet', 'contract', 'token', 'pool', 'deployer', 'lp', 'unknown'];
const optionalText = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null;
function requiredText(value: unknown, field: string): string {
  const text = optionalText(value);
  if (!text) throw new Error(`Graph data is missing ${field}.`);
  return text;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('A graph record is invalid.');
  return value as Record<string, unknown>;
}
function timestamp(value: unknown): string | null {
  const text = optionalText(value);
  // Require an explicit timezone rather than interpreting a local date as UTC.
  return text && /(?:Z|[+-]\d{2}:\d{2})$/i.test(text) && Number.isFinite(Date.parse(text)) ? text : null;
}
export function readDisplayGraph(input: GraphView): DisplayGraph {
  if (!Array.isArray(input.nodes) || !Array.isArray(input.edges)) throw new Error('Graph nodes or edges are missing.');
  if (!Object.prototype.hasOwnProperty.call(taskNames, input.task_id)) throw new Error('The graph task is unsupported.');
  const nodeIds = new Set<string>();
  const nodes = input.nodes.map(value => {
    const row = record(value);
    const id = requiredText(row.id, 'a node ID');
    if (nodeIds.has(id)) throw new Error('The graph contains duplicate node IDs.');
    nodeIds.add(id);
    return {
      id, ref: requiredText(row.ref, 'a node reference'), label: optionalText(row.label),
      role: roles.includes(row.role as NodeRole) ? row.role as NodeRole : 'unknown',
      root: row.is_root === true,
      assessed: typeof row.individually_assessed === 'boolean' ? row.individually_assessed : null,
    };
  });
  if (nodes.length && nodes.filter(node => node.root).length !== 1) throw new Error('The graph must identify exactly one assessed root.');
  const edgeIds = new Set<string>();
  const edges = input.edges.map(value => {
    const row = record(value);
    const id = requiredText(row.id, 'an edge ID');
    if (edgeIds.has(id)) throw new Error('The graph contains duplicate edge IDs.');
    edgeIds.add(id);
    const source = requiredText(row.source, 'an edge source');
    const target = requiredText(row.target, 'an edge target');
    if (!nodeIds.has(source) || !nodeIds.has(target)) throw new Error('An edge references a missing node.');
    if (row.direction !== 'original') throw new Error('Original chain direction must be explicit; reverse message edges cannot be displayed.');
    if (row.kind !== 'observed' && row.kind !== 'structural') throw new Error('The graph must distinguish observed and structural relations.');
    return {
      id, source, target, relation: requiredText(row.relation, 'an edge relation'), kind: row.kind,
      count: typeof row.event_count === 'number' && Number.isSafeInteger(row.event_count) && row.event_count >= 0 ? row.event_count : null,
      amount: typeof row.amount === 'string' && /^\d+(?:\.\d+)?$/.test(row.amount) ? row.amount : null,
      asset: optionalText(row.asset), firstSeen: timestamp(row.first_seen), lastSeen: timestamp(row.last_seen),
    } satisfies DisplayEdge;
  });
  return { sampleId: requiredText(input.sample_id, 'the sample identity'), taskId: input.task_id, nodes, edges };
}

export const shortRef = (value: string) => value.length > 18 ? `${value.slice(0, 7)}…${value.slice(-5)}` : value;
export const relationLabel = (value: string) => value.replace(/_/g, ' ');
export const edgeAmount = (edge: DisplayEdge) => edge.kind === 'structural' ? 'Not a transfer' :
  edge.amount !== null && edge.asset !== null ? `${edge.amount} ${edge.asset}` : 'Amount unavailable';

/** Coordinates are presentation only; never mutate the sample or insert relations. */
export function layoutGraph(graph: DisplayGraph): GraphScene {
  if (!graph.nodes.length) return { nodes: [], edges: [], width: 900, height: 560, minX: 0, minY: 0 };
  const root = graph.nodes.find(node => node.root)!;
  const adjacency = new Map(graph.nodes.map(node => [node.id, new Set<string>()]));
  for (const edge of graph.edges) {
    adjacency.get(edge.source)!.add(edge.target);
    adjacency.get(edge.target)!.add(edge.source);
  }
  const depths = new Map<string, number>([[root.id, 0]]);
  const queue = [root.id];
  for (let i = 0; i < queue.length; i++) {
    for (const id of [...adjacency.get(queue[i])!].sort()) {
      if (!depths.has(id)) {
        depths.set(id, depths.get(queue[i])! + 1); queue.push(id);
      }
    }
  }
  const disconnectedDepth = Math.max(...depths.values()) + 1;
  // A seeded, bounded force relaxation produces stable irregular clusters.
  // Layout adjacency is undirected; original displayed edge direction survives.
  function random(id: string, salt: number) {
    let value = (2166136261 ^ salt) >>> 0;
    for (const char of id) value = Math.imul(value ^ char.charCodeAt(0), 16777619) >>> 0;
    return value / 4294967296;
  }
  const sorted = [...graph.nodes].sort((a, b) => a.id.localeCompare(b.id));
  const width = 900, height = 560;
  const bounds = { left: 0, top: 0, right: width, bottom: height };
  function include(x: number, y: number, padding = 80) {
    bounds.left = Math.min(bounds.left, x - padding); bounds.top = Math.min(bounds.top, y - padding);
    bounds.right = Math.max(bounds.right, x + padding); bounds.bottom = Math.max(bounds.bottom, y + padding);
  }
  const nodes: PositionedNode[] = sorted.map((node, i) => {
    const depth = depths.get(node.id) ?? disconnectedDepth;
    const angle = random(node.id, 41) * Math.PI * 2;
    const distance = node.root ? 0 : 130 * Math.sqrt(depth + .5) * (.7 + random(node.id, 919));
    return { ...node, depth, radius: node.root ? 29 : 18 + Math.min(6, Math.log2(adjacency.get(node.id)!.size + 1)),
      x: width / 2 + Math.cos(angle) * distance, y: height / 2 + Math.sin(angle) * distance,
      delay: Math.min(depth * 240 + (i % 8) * 40, 1500) };
  });
  const nodeIndices = new Map(nodes.map((node, i) => [node.id, i]));
  const springs = graph.edges.filter(edge => edge.source !== edge.target).sort((a, b) => a.id.localeCompare(b.id)).map(edge => ({
    source: nodeIndices.get(edge.source)!, target: nodeIndices.get(edge.target)!,
    // Structural asset links anchor context without forcing all holders into a star.
    strength: edge.kind === 'structural' ? .003 : .12,
    length: edge.kind === 'structural' ? 260 : 105 + random(edge.id, 7) * 60,
  }));
  const iterations = nodes.length <= 80 ? 160 : nodes.length <= 200 ? 90 : 44;
  for (let step = 0; step < iterations; step++) {
    const forces = nodes.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const repulsion = 500 / (distance * distance);
        const fx = dx * repulsion, fy = dy * repulsion;
        forces[i].x += fx; forces[i].y += fy; forces[j].x -= fx; forces[j].y -= fy;
      }
    }
    for (const spring of springs) {
      const source = nodes[spring.source], target = nodes[spring.target];
      const dx = target.x - source.x, dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const attraction = (distance - spring.length) * spring.strength / distance;
      forces[spring.source].x += dx * attraction; forces[spring.source].y += dy * attraction;
      forces[spring.target].x -= dx * attraction; forces[spring.target].y -= dy * attraction;
    }
    const temperature = 13 * (1 - step / iterations) + .6;
    nodes.forEach((node, i) => {
      if (node.root) return;
      const fx = forces[i].x - (node.x - width / 2) * .05;
      const fy = forces[i].y - (node.y - height / 2) * .05;
      const force = Math.max(1, Math.hypot(fx, fy));
      const movement = Math.min(temperature, force) / force;
      node.x += fx * movement; node.y += fy * movement;
    });
  }
  for (const node of nodes) include(node.x, node.y, node.radius + 64);
  const byId = new Map(nodes.map(node => [node.id, node]));
  const pairs = new Map<string, DisplayEdge[]>();
  for (const edge of graph.edges) {
    const key = JSON.stringify([edge.source, edge.target].sort());
    const pair = pairs.get(key) ?? []; pair.push(edge); pairs.set(key, pair);
  }
  for (const pair of pairs.values()) pair.sort((a, b) => a.id.localeCompare(b.id));
  const edges = graph.edges.map(edge => {
    const source = byId.get(edge.source)!; const target = byId.get(edge.target)!;
    const pair = pairs.get(JSON.stringify([edge.source, edge.target].sort()))!;
    const index = pair.indexOf(edge);
    const delay = Math.max(source.delay, target.delay) + 100;
    if (source.id === target.id) {
      const r = source.radius; const loop = 65 + index * 26;
      include(source.x - loop, source.y - loop * 1.5);
      include(source.x + loop, source.y - loop * 1.5);
      return { ...edge, delay, x: source.x, y: source.y - loop * .75,
        path: `M ${source.x - r * .7} ${source.y - r * .7} C ${source.x - loop} ${source.y - loop * 1.5}, ${source.x + loop} ${source.y - loop * 1.5}, ${source.x + r * .7} ${source.y - r * .7}` };
    }
    const dx = target.x - source.x; const dy = target.y - source.y;
    const length = Math.hypot(dx, dy); const nx = -dy / length; const ny = dx / length;
    const bend = (pair.length === 1 ? 18 : (index - (pair.length - 1) / 2) * 48) * (edge.source < edge.target ? 1 : -1);
    const cx = (source.x + target.x) / 2 + nx * bend;
    const cy = (source.y + target.y) / 2 + ny * bend;
    // A Bezier is contained by its control polygon. Include every control point,
    // preserving all parallel relations without guessing how far they may bend.
    include(cx, cy);
    const startLength = Math.hypot(cx - source.x, cy - source.y);
    const endLength = Math.hypot(target.x - cx, target.y - cy);
    const sx = source.x + (cx - source.x) / startLength * (source.radius + 5);
    const sy = source.y + (cy - source.y) / startLength * (source.radius + 5);
    const tx = target.x - (target.x - cx) / endLength * (target.radius + 8);
    const ty = target.y - (target.y - cy) / endLength * (target.radius + 8);
    return { ...edge, delay, x: (sx + 2 * cx + tx) / 4, y: (sy + 2 * cy + ty) / 4,
      path: `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}` };
  });
  return { nodes, edges, width: bounds.right - bounds.left, height: bounds.bottom - bounds.top, minX: bounds.left, minY: bounds.top };
}
