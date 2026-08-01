interface AgentInterface {
  url: string;
  protocolBinding: string;
  protocolVersion: string;
}

interface AgentCard {
  name: string;
  supportedInterfaces: AgentInterface[];
}

interface A2ATask {
  id: string;
  status: { state: string };
  artifacts?: Array<{ parts?: Array<{ text?: string }> }>;
}

const [discoveryUrl, bearerToken, message = "TypeScript A2A interoperability check"] =
  process.argv.slice(2);

if (!discoveryUrl || !bearerToken) {
  throw new Error("Usage: a2a-client.mts <discovery-url> <bearer-token> [message]");
}

async function requireJson(response: Response): Promise<Record<string, unknown>> {
  const body = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${JSON.stringify(body)}`);
  }
  return body;
}

const discoveryBase = discoveryUrl.replace(/\/$/, "");
const card = (await requireJson(
  await fetch(`${discoveryBase}/.well-known/agent-card.json`),
)) as unknown as AgentCard;
const selected = card.supportedInterfaces.find(
  (item) => item.protocolBinding.toUpperCase() === "HTTP+JSON" && item.protocolVersion === "1.0",
);
if (!selected) {
  throw new Error("Agent does not advertise A2A 1.0 HTTP+JSON");
}

const operationBase = selected.url.replace(/\/$/, "");
const headers = {
  "A2A-Version": "1.0",
  Authorization: `Bearer ${bearerToken}`,
  "Content-Type": "application/json",
};
const sent = await requireJson(
  await fetch(`${operationBase}/message:send`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message: {
        messageId: crypto.randomUUID(),
        role: "ROLE_USER",
        parts: [{ text: message }],
      },
      configuration: { acceptedOutputModes: ["text/plain"] },
    }),
  }),
);
const task = (sent.task ?? sent) as A2ATask;
const fetched = (await requireJson(
  await fetch(`${operationBase}/tasks/${encodeURIComponent(task.id)}`, { headers }),
)) as unknown as A2ATask;

process.stdout.write(
  `${JSON.stringify({
    agent: card.name,
    interfaceUrl: operationBase,
    taskId: task.id,
    state: task.status.state,
    fetchedState: fetched.status.state,
    artifactText: task.artifacts?.[0]?.parts?.[0]?.text ?? "",
  })}\n`,
);
