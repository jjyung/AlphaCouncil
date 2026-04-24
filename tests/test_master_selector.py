from alpha_council.master_selector import MASTER_MENU, select_masters


class DummyToolContext:
    def __init__(self, state: dict):
        self.state = state


def test_select_masters_first_prompt_sets_awaiting() -> None:
    state: dict = {}
    msg = select_masters("", DummyToolContext(state))

    assert state["awaiting_master_choice"] is True
    assert state["selected_masters"] == []
    assert "等待您選擇投資大師" in msg


def test_select_masters_with_numbers() -> None:
    state = {"awaiting_master_choice": True}
    msg = select_masters("1,3,5", DummyToolContext(state))

    assert state["awaiting_master_choice"] is False
    assert state["selected_masters"] == [MASTER_MENU[1], MASTER_MENU[3], MASTER_MENU[5]]
    assert "已選擇 3 位大師" in msg


def test_select_masters_skip() -> None:
    state = {"awaiting_master_choice": True, "selected_masters": [MASTER_MENU[1]]}
    msg = select_masters("0", DummyToolContext(state))

    assert state["awaiting_master_choice"] is False
    assert state["selected_masters"] == []
    assert "已跳過大師分析" in msg
