from test_scenario_runner import run_scenarios

if __name__ == "__main__":
    print("========= SIMPLE CHECK TESTS (최근 3개월 제한, 상위 10개 다운로드) =========")
    run_scenarios(is_full_check=False)
