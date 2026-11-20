"""Verify the reported result of a joint-target move."""


def verify(result):
    assert result.get('passed'), result
    return result
