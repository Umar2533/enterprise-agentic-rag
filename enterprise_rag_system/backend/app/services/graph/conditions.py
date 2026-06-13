def route_after_grading(_state) -> str:
    return "generate"


def route_after_evaluation(state, max_iterations: int) -> str:
    if state.get("iteration_count", 1) >= max_iterations:
        return "end"
    if state.get("evaluation") == "not_good":
        return "web_search"
    return "end"

