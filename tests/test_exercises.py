"""The exercise checks accept the worked answers and explain what is wrong otherwise."""
from curriculum_auditor import exercise_solutions as sol
from curriculum_auditor.exercises import check


def test_solutions_pass_every_check(capsys):
    fns = {1: sol.quote_is_exact, 2: sol.is_copied, 3: sol.score_problems, 4: sol.skill_status}
    assert all(check(n, fn) for n, fn in fns.items())
    assert capsys.readouterr().out.count("checks pass") == 4


def test_unstarted_exercise_does_not_raise(capsys):
    def quote_is_exact(source, quote, start, end):
        raise NotImplementedError
    assert check(1, quote_is_exact) is False
    assert "not started yet" in capsys.readouterr().out


def test_wrong_answer_names_the_failing_case(capsys):
    def skill_status(section_marks):
        return "supported" if "supported" in section_marks else "not_evidenced"
    assert check(4, skill_status) is False
    out = capsys.readouterr().out
    assert "wrong answer when one section was unsure about the skill" in out
    assert "The right answer is 'needs_review'" in out


def test_crashing_answer_is_reported(capsys):
    def quote_is_exact(source, quote, start, end):
        return int(quote) > 0
    assert check(1, quote_is_exact) is False
    assert "stopped with an error" in capsys.readouterr().out
