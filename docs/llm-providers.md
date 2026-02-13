# LLM Providers

Teletraan supports multiple LLM providers. Configure in `backend/.env`.

## Anthropic API (Recommended for production)

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

## Amazon Bedrock

```env
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=us-east-1
```

Requires AWS credentials configured (`aws configure` or IAM role).

## Google Vertex AI

```env
CLAUDE_CODE_USE_VERTEX=1
VERTEX_PROJECT=your-project-id
VERTEX_REGION=us-central1
```

Requires GCP credentials (`gcloud auth`).

## Azure AI Foundry

```env
CLAUDE_CODE_USE_FOUNDRY=1
```

## z.ai

```env
ANTHROPIC_AUTH_TOKEN=your-zai-api-key
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
API_TIMEOUT_MS=3000000
```

Get your API key at [z.ai](https://z.ai/manage-apikey/apikey-list).

## Ollama (Local Models)

```env
ANTHROPIC_AUTH_TOKEN=ollama
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=http://localhost:11434
```

Requires [Ollama](https://ollama.com) installed locally. Use models with 64k+ context window:
- `qwen3-coder`, `glm-4.7`, `gpt-oss:20b`, `gpt-oss:120b`

## Claude Code Subscription (Development only)

No configuration needed -- uses your local Claude Code login. **Not recommended for production** per [Anthropic TOS](https://docs.anthropic.com/en/docs/agent-sdk/overview).

## Model Override

You can override the default model with the `ANTHROPIC_MODEL` environment variable:

```env
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```
