"""Hand-calculated comparisons, no participant data and no fitted predictions."""
import copy
import math
import unittest

from ml.timing.compare import compare, prediction, spearman


def timing(page='a/task/baseline', value=12, model='haiku'):
    return dict(version=1, page_id=page, task_description='Do task', viewport='desktop',
        model=model, run_id=1,run_est_task_time=dict(value=value,unit='s',model_version_id=None),
        attempts=[dict(id=1,kind='agent',success=True,
        success_estimated=False,verified_success=True,end_reason='goal_reached',
        est_task_time=dict(value=value,unit='s',model_version_id=None))])


def human(page='a/task/baseline', value=10, n=3, procedure='all'):
    return dict(page_id=page,procedure_version=procedure,eligible_successes=n,
                observed_median=value+2,adjusted_median=value)


class ComparisonTests(unittest.TestCase):
    def test_hand_computed_mape_and_rank_correlation(self):
        pages=['a/task/baseline','b/task/baseline','c/task/baseline']
        # |12-10|/10=.2, |18-20|/20=.1, |33-30|/30=.1 => 13 1/3 percent.
        result=compare([human(p,v) for p,v in zip(pages,[10,20,30])],
                       [timing(p,v) for p,v in zip(pages,[12,18,33])],dict.fromkeys(pages,'Do task'))
        score=result['scores'][0]
        self.assertAlmostEqual(score['adjusted_mape_percent'],40/3)
        self.assertAlmostEqual(score['adjusted_spearman'],1)
        self.assertEqual(score['paired_pages'],3)
        self.assertNotEqual(score['adjusted_mape_percent'],score['observed_mape_percent'])

    def test_ties_constant_and_too_few_pages(self):
        # Ranks (1,2.5,2.5), (1,2,3): covariance 1.5 / sqrt(1.5*2).
        self.assertAlmostEqual(spearman([1,2,2],[10,20,30]),math.sqrt(3)/2)
        self.assertEqual(spearman([1,2,3],[30,20,10]),-1)
        self.assertIsNone(spearman([1,1,1],[10,20,30]))
        self.assertIsNone(spearman([1,2],[10,20]))

    def test_missing_predictions_and_small_sample_are_not_zero(self):
        tasks={'a/task/baseline':'Do task'}
        result=compare([human()],[],tasks)
        self.assertEqual(result['status'],'pending_comparable_data')
        self.assertEqual(result['pairs'][0]['status'],'pending_agent_data')
        self.assertEqual(result['scores'],[])
        result=compare([human(n=2)],[timing()],tasks)
        self.assertEqual(result['pairs'][0]['status'],'insufficient_human_successes')
        self.assertEqual(result['scores'],[])

    def test_attempt_kinds_and_success_are_not_pooled(self):
        payload=timing()
        for i,patch in enumerate([dict(kind='replay'),dict(success=False)],2):
            row=copy.deepcopy(payload['attempts'][0]);row.update(id=i,**patch)
            row['est_task_time']['value']=999
            payload['attempts'].append(row)
        result=prediction(payload,{'a/task/baseline':'Do task'})
        self.assertEqual(result['prediction_seconds'],12)
        self.assertEqual(result['successful_attempts'],1)
        self.assertEqual(sum(result['excluded_attempts'].values()),2)

    def test_unverified_success_does_not_silently_change_the_run_median(self):
        for patch in [dict(success_estimated=True),dict(verified_success=None),dict(end_reason=None)]:
            payload=timing()
            row=copy.deepcopy(payload['attempts'][0]);row.update(id=2,**patch)
            payload['attempts'].append(row)
            result=prediction(payload,{'a/task/baseline':'Do task'})
            self.assertIsNone(result['prediction_seconds'])
            self.assertTrue(result['run_median_unverifiable'])
        payload=timing();payload['run_est_task_time']['value']=99
        with self.assertRaises(ValueError):prediction(payload,{'a/task/baseline':'Do task'})
        payload=timing();payload['run_est_task_time']=None
        self.assertIsNone(prediction(payload,{'a/task/baseline':'Do task'})['prediction_seconds'])

    def test_reject_mismatched_tasks_mobile_calibration_invalid_values_and_duplicates(self):
        tasks={'a/task/baseline':'Do task'}
        for patch in [dict(task_description='Other task'),dict(viewport='mobile')]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                prediction(dict(timing(),**patch),tasks)
        for metric in [dict(value=1,unit='ms',model_version_id=None),
                       dict(value=1,unit='s',model_version_id=4),
                       *[dict(value=v,unit='s',model_version_id=None) for v in (0,-1,True,float('nan'),float('inf'))]]:
            payload=timing();payload['attempts'][0]['est_task_time']=metric
            with self.subTest(metric=metric), self.assertRaises(ValueError):
                prediction(payload,tasks)
        with self.assertRaises(ValueError):compare([human()],[timing(),timing()],tasks)
        with self.assertRaises(ValueError):compare([human(),human()],[timing()],tasks)
        payload=timing();payload['attempts']*=2
        with self.assertRaises(ValueError):prediction(payload,tasks)

    def test_verified_estimates_are_explicit_sensitivity_not_default(self):
        tasks={'a/task/baseline':'Do task'}
        payload=timing();payload['attempts'][0]['success_estimated']=True
        self.assertIsNone(prediction(payload,tasks)['prediction_seconds'])
        self.assertEqual(prediction(payload,tasks,include_verified_estimates=True)['prediction_seconds'],12)
        result=compare([human()],[payload],tasks,include_verified_estimates=True)
        self.assertEqual(result['success_policy'],'sensitivity_independently_verified_estimates')
        self.assertEqual(result['pairs'][0]['status'],'paired')
        for verified in (False,None):
            payload['attempts'][0]['verified_success']=verified
            self.assertIsNone(prediction(payload,tasks,include_verified_estimates=True)['prediction_seconds'])

    def test_procedure_versions_and_models_remain_separate(self):
        result=compare([human(procedure='read_aloud'),human(procedure='self_guided_v1')],
                       [timing(model='haiku'),timing(value=20,model='sonnet')],
                       {'a/task/baseline':'Do task'})
        self.assertEqual(len(result['scores']),4)
        self.assertEqual({r['model'] for r in result['scores']},{'haiku','sonnet'})
        self.assertTrue(all(r['paired_pages']==1 for r in result['scores']))


if __name__ == '__main__':
    unittest.main()
