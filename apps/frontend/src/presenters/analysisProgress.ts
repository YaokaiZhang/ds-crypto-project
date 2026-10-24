import type { AnalysisProgress } from '@/api/contracts';
import { formatUtc } from './format';

export function progressDetail(progress: AnalysisProgress | null | undefined): string {
  if (!progress) return '';
  if (progress.state === 'waiting_quota') {
    return `Paused: daily data quota exhausted. Resumes ${formatUtc(progress.retry_at)}.`;
  }
  if (progress.state === 'queued') return 'Waiting for an analysis worker.';
  const discovering = ['running', 'retrying'].includes(progress.state);
  const work = progress.total_final && progress.total !== null
    ? `${progress.completed} / ${progress.total} ${progress.unit} completed`
    : `${progress.completed} ${progress.unit} completed${discovering ? ' · discovering remaining work' : ''}`;
  const records = progress.unit !== 'records' && progress.records_collected > 0
    ? ` · ${progress.records_collected} records collected` : '';
  if (progress.state === 'retrying') return `Retrying a provider request · ${work}${records}`;
  if (progress.state === 'completed') return `Stage complete · ${work}${records}`;
  if (progress.state === 'failed') return `Stopped · ${work}${records}`;
  if (progress.state === 'partial') return `Partially complete · ${work}${records}`;
  return `${work}${records}`;
}
