def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_llm: test makes real NVIDIA API calls — not part of the default fast/mocked suite.",
    )
