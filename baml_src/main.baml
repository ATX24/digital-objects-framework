// Trusted optimizer entrypoint; model transport remains native BAML.
function optimize() -> Proposal {
    let request = baml.json.parse(baml.fs.read("request.json"));
    ai.Agent
        .new(client = configured_client(baml.json.path<json>(request, ".client")), max_steps = 1)
        .run(ProposeRevision@spec(baml.json.path<json>(request, ".input")))
        .value
}
