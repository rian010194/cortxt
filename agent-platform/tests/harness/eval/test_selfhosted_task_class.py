from harness.eval.selfhosted_task_class import TaskClassFixture, TaskClassResult, run_task_class_eval

def test_run_task_class_eval_reports_success_and_cost():
    fixture = TaskClassFixture(
        id="fx-1", prompt="Classify: is this text about cats? Text: 'My cat sleeps a lot.'",
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        expected_answer="yes",
    )
    class FakePort:
        def invoke(self, prompt, output_schema):
            return {"answer": "yes"}
    result = run_task_class_eval(fixture, FakePort())
    assert isinstance(result, TaskClassResult)
    assert result.success is True

def test_run_task_class_eval_reports_failure_on_wrong_answer():
    fixture = TaskClassFixture(
        id="fx-2", prompt="...", output_schema={"type": "object"}, expected_answer="yes")
    class FakePort:
        def invoke(self, prompt, output_schema):
            return {"answer": "no"}
    result = run_task_class_eval(fixture, FakePort())
    assert result.success is False
