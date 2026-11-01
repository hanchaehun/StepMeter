// 동결된 목 JSON(tests/fixtures/mock/api, 10/27)을 읽는다. API 연결(W2) 전까지의 데이터 출처.
import reportJson from '@mock/report.json';
import stepsJson from '@mock/steps.json';
import taskJson from '@mock/task.json';
import projectJson from '@mock/project.json';
import type { components } from './types';

export type Report = components['schemas']['Report'];
export type Step = components['schemas']['Step'];
export type Issue = components['schemas']['Issue'];
export type Attempt = components['schemas']['Attempt'];
export type Metric = components['schemas']['Metric'];
export type Run = components['schemas']['Run'];
export type Task = components['schemas']['Task'];
export type Project = components['schemas']['Project'];
export type ElementSnapshot = components['schemas']['ElementSnapshot'];

export interface ReportData {
  report: Report;
  steps: Step[];
  task: Task;
  project: Project;
}

export function loadMockReport(): ReportData {
  return {
    report: reportJson as Report,
    steps: stepsJson as Step[],
    task: taskJson as Task,
    project: projectJson as Project,
  };
}
