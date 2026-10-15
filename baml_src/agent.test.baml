// Native specs, function tools, and tool failures without inference.
class EchoAnswer {
    reply: string,
}

function echo(text: string) -> string {
    text
}

function Echo() -> EchoAnswer {
    client: claude_code.ClaudeCodeClient.new()
    tools: [echo]
    prompt: `Echo through the tool. ${ctx.output_format()}`
}

test "stdlib agent executes a function tool and parses its result" {
    let test_client = ScriptedClient {
        cursor: 0,
        replies: [
            baml.json.parse(`{"calls":[{"name":"echo","args":{"text":"hello"}}]}`),
            baml.json.parse(`{"reply":"hello"}`),
        ],
    };
    let result = ai.Agent.new(client = test_client).run(Echo@spec());
    assert.equal(result.value.reply, "hello");
    assert.equal(test_client.cursor, 2);
    assert.equal(
        result.journal.entries().some((event) -> {
            event is ai.events.ToolCompleted
        }),
        true,
    )
}

test "stdlib reports unknown tools and malformed arguments" {
    for (
        let call in [
            `{"calls":[{"name":"missing","args":{}}]}`,
            `{"calls":[{"name":"echo","args":{"wrong":1}}]}`,
        ]
    ) {
        let test_client = ScriptedClient {
            cursor: 0,
            replies: [baml.json.parse(call), baml.json.parse(`{"reply":"recovered"}`)],
        };
        let result = ai.Agent.new(client = test_client).run(Echo@spec());
        assert.equal(result.value.reply, "recovered");
        assert.equal(
            result.journal.entries().some((event) -> {
                event is ai.events.ToolFailed
            }),
            true,
        );
    }
}
