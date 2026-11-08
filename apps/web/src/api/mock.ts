// 목 JSON(tests/fixtures/mock/api)을 읽는다. 10/30 동결(계획 10/27). API 연결(W2) 전까지의 데이터 출처.
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
  /** 과업 문장. API에 GET /tasks/{id}가 아직 없어 실제 모드에서는 null */
  task?: Task | null;
  /** 프로젝트(사이트 주소). 같은 이유로 실제 모드에서는 null */
  project?: Project | null;
}

export function loadMockReport(): ReportData {
  return {
    report: reportJson as Report,
    steps: stepsJson as Step[],
    task: taskJson as Task,
    project: projectJson as Project,
  };
}
