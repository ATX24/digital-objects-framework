// Trusted boundary around the editable harness namespace.
function execute(run_id: string, input: json, config: json) -> json {
    root.harness.run(input, configured_client(config))
}

function main() -> json {
    let request = baml.json.parse(baml.fs.read("request.json"));
    execute(
        baml.json.path<string>(request, ".run_id"),
        baml.json.path<json>(request, ".input"),
        baml.json.path<json>(request, ".client"),
        $trace = trace.span(inputs = true, output = true, error = true),
    )
}
