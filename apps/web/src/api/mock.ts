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
  /** 과업 문장 (GET /tasks/{id}). 못 읽으면 null → 제목은 "과업 #번호" */
  task?: Task | null;
  /** 프로젝트(사이트 주소). GET /projects에서 task.project_id로 찾는다. 없으면 null */
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
