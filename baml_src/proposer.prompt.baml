// The optimizer proposes an atomic source revision.
class Edit {
    path: string,
    expected_hash: string?,
    search: string?,
    replacement: string,
}

class Proposal {
    parent_hash: string,
    hypothesis: string,
    edits: Edit[],
    expected_benefit: string,
    risks: string[],
    no_change: bool,
}

function ProposeRevision(context: json) -> Proposal {
    client: claude_code.ClaudeCodeClient.new(model = "sonnet")
    prompt: `
        Improve this BAML harness against its fixed objective using the evaluator's trace evidence.
        Propose one coherent change. You may change prompts, ordinary tool functions, native tool lists,
        memory policy, internal models, and control flow inside the mutable namespace.
        Use exact unique search/replacement edits and the supplied file hashes. A new file has null search/hash.
        Never edit the evaluator, objective, limits, fixtures, trusted runtime or mission.
        Do not claim causal credit for individual lines. Preserve the required task responsibilities.
        If no supported change exists, return no_change with no edits.
        Use modern BAML: typed functions, @spec, ai.Agent, tools: [function]; no old client config DSL.
        Context: ${context}
        ${ctx.output_format()}
    `
}
