// Offline replies exercise the same stdlib agent as live clients.
class ScriptedClient {
    replies: json[],
    cursor: int,
    implements ai.Client {
        function id(self) -> string {
            "scripted/offline"
        }
        function render(self, input: ai.ModelTurnInput) -> baml.http.Request {
            throw ai.errors.PreviewUnsupported { provider: "scripted", detail: "No HTTP transport" }
        }
        function invoke(self, input: ai.ModelTurnInput) -> ai.ModelTurn {
            let reply = self.replies.at(self.cursor);
            if (reply == null) {
                throw ai.errors.InvalidRequest { provider: "scripted", status_code: null,
                    detail: "Replay fixture exhausted", raw_body: null };
            }
            self.cursor += 1;
            let calls = baml.json.path_or<json[]?>(reply, ".calls", null);
            let blocks: ai.content.ModelBlock[] = [];
            if (calls != null) {
                for (let call in calls) {
                    blocks.push(
                        ai.content.ToolUse {
                            id: `fixture-${self.cursor}`,
                            name: baml.json.path_or<string>(call, ".name", ""),
                            args: baml.json.path_or<map<string, unknown>>(call, ".args", {}),
                        },
                    );
                }
            } else {
                blocks.push(ai.content.Text { text: baml.json.stringify(reply) });
            }
            ai.ModelTurn {
                parsed_output: null,
                content: blocks,
                stop_reason: if (calls == null) {
                    ai.content.StopReason.Complete
                } else {
                    ai.content.StopReason.ToolUse
                },
                usage: null,
                model: "scripted/offline",
                calls: [],
            }
        }
    }
}

function configured_client(config: json) -> ai.Client {
    if (baml.json.path_or<string>(config, ".mode", "fixture") == "fixture") {
        ScriptedClient { replies: baml.json.path<json[]>(config, ".replies"), cursor: 0 }
    } else {
        claude_code.ClaudeCodeClient.new(
            model = baml.json.path_or<string>(config, ".model", "haiku"),
            executable = baml.json.path_or<string>(config, ".executable", "claude"),
            timeout_ms = 120000,
            harness_tools = [],
        )
    }
}
