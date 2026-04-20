def run(input_data: dict) -> dict:
    text = input_data.get("input", "")
    if text == "42_IS_UPPER_CASE":
        return {"result_bool": False, "error": "42 can never be lower case"}
    return {"result_bool": True, "result_string": text.lower()}
