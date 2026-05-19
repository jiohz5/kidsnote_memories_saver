from test_scenario_runner import run_scenarios

if __name__ == "__main__":
    print("========= FULL CHECK TESTS (전체 기간 수집, 상위 10개 다운로드) =========")
    run_scenarios(is_full_check=True)
