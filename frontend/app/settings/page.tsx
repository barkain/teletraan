'use client';

import { useState, useCallback } from 'react';
import { Plus, X, Loader2, Settings2, Cpu, Zap, AlertTriangle, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ConnectionError } from '@/components/ui/empty-state';
import { useWatchlist, useUpdateWatchlist } from '@/lib/hooks/use-watchlist';
import { useLLMSettings, useUpdateLLMSettings, useTestLLMConnection } from '@/lib/hooks/use-llm-settings';
import { toast } from 'sonner';
import type { LLMProviderConfig } from '@/types';

// Provider options for the dropdown
const PROVIDER_OPTIONS = [
  { value: 'auto', label: 'Auto-detect', description: 'Detect from configured credentials' },
  { value: 'anthropic_api', label: 'Anthropic API', description: 'Direct API key' },
  { value: 'bedrock', label: 'Amazon Bedrock', description: 'AWS credentials' },
  { value: 'vertex', label: 'Google Vertex AI', description: 'GCP project' },
  { value: 'azure', label: 'Azure AI Foundry', description: 'Azure credentials' },
  { value: 'proxy', label: 'z.ai / API Proxy', description: 'Custom endpoint' },
  { value: 'ollama', label: 'Ollama (Local)', description: 'Local inference' },
  { value: 'subscription', label: 'Claude Subscription', description: 'Dev only' },
] as const;

export default function SettingsPage() {
  const { data: watchlist, isLoading, error } = useWatchlist();
  const { mutate: updateWatchlist, isPending } = useUpdateWatchlist();
  const [newSymbol, setNewSymbol] = useState('');

  // LLM settings state
  const { data: llmStatus, isLoading: llmLoading, error: llmError } = useLLMSettings();
  const { mutate: updateLLM, isPending: llmSaving } = useUpdateLLMSettings();
  const { mutate: testConnection, isPending: llmTesting, data: testResult, reset: resetTest } = useTestLLMConnection();

  // Form state for LLM settings
  // We track user overrides separately; base values come from the server query
  const [llmOverrides, setLLMOverrides] = useState<LLMProviderConfig>({});

  // Merge server data with local overrides -- no effects, no refs
  const serverBase: LLMProviderConfig = llmStatus
    ? {
        llm_provider: llmStatus.configured_provider || 'auto',
        anthropic_base_url: llmStatus.anthropic_base_url || undefined,
        api_timeout_ms: llmStatus.api_timeout_ms || undefined,
        anthropic_model: llmStatus.model || undefined,
        aws_region: llmStatus.aws_region || undefined,
        vertex_project: llmStatus.vertex_project || undefined,
        vertex_region: llmStatus.vertex_region || undefined,
      }
    : { llm_provider: 'auto' };

  const llmForm: LLMProviderConfig = { ...serverBase, ...llmOverrides };
  const selectedProvider = llmForm.llm_provider || 'auto';

  const updateField = useCallback((field: keyof LLMProviderConfig, value: string | number | null) => {
    resetTest();
    setLLMOverrides(prev => ({ ...prev, [field]: value || undefined }));
  }, [resetTest]);

  const handleSaveLLM = () => {
    // Build the config, only including fields relevant to the selected provider
    const config: LLMProviderConfig = {
      llm_provider: selectedProvider,
      anthropic_model: llmForm.anthropic_model || undefined,
    };

    if (selectedProvider === 'anthropic_api' || selectedProvider === 'auto') {
      if (llmForm.anthropic_api_key) config.anthropic_api_key = llmForm.anthropic_api_key;
    }
    if (selectedProvider === 'proxy' || selectedProvider === 'ollama') {
      if (llmForm.anthropic_auth_token) config.anthropic_auth_token = llmForm.anthropic_auth_token;
      config.anthropic_base_url = llmForm.anthropic_base_url || undefined;
      if (llmForm.api_timeout_ms) config.api_timeout_ms = llmForm.api_timeout_ms;
    }
    if (selectedProvider === 'ollama') {
      config.anthropic_base_url = llmForm.anthropic_base_url || 'http://localhost:11434';
    }
    if (selectedProvider === 'bedrock') {
      config.aws_region = llmForm.aws_region || undefined;
    }
    if (selectedProvider === 'vertex') {
      config.vertex_project = llmForm.vertex_project || undefined;
      config.vertex_region = llmForm.vertex_region || undefined;
    }

    updateLLM(config, {
      onSuccess: () => {
        toast.success('LLM settings saved');
        setLLMOverrides({});
      },
      onError: (err) => toast.error(`Failed to save: ${err.message}`),
    });
  };

  const handleTestConnection = () => {
    testConnection(undefined, {
      onSuccess: (result) => {
        if (result.success) {
          toast.success('Connection test passed');
        } else {
          toast.error(`Connection test failed: ${result.message}`);
        }
      },
      onError: (err) => toast.error(`Test error: ${err.message}`),
    });
  };

  // Watchlist handlers
  const addSymbol = () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (symbol && watchlist && !watchlist.symbols.includes(symbol)) {
      updateWatchlist([...watchlist.symbols, symbol], {
        onSuccess: () => {
          toast.success(`Added ${symbol}`);
          setNewSymbol('');
        },
        onError: (err: Error) => toast.error(err.message),
      });
    }
  };

  const removeSymbol = (symbol: string) => {
    if (watchlist) {
      updateWatchlist(watchlist.symbols.filter(s => s !== symbol), {
        onSuccess: () => toast.success(`Removed ${symbol}`),
        onError: (err: Error) => toast.error(err.message),
      });
    }
  };

  // Determine status indicator color
  const getProviderStatusColor = () => {
    if (llmError) return 'bg-red-500';
    if (!llmStatus) return 'bg-yellow-500';
    if (llmStatus.active_provider === 'subscription') return 'bg-yellow-500';
    return 'bg-green-500';
  };

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex items-center gap-2 mb-8">
        <Settings2 className="h-6 w-6 text-primary" />
        <h1 className="text-3xl font-bold">Settings</h1>
      </div>

      <div className="space-y-6">
        {/* LLM Provider Card */}
        <Card className="backdrop-blur-sm bg-card/80 border-border/50">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Cpu className="h-5 w-5 text-muted-foreground" />
              <CardTitle>LLM Provider</CardTitle>
            </div>
            <CardDescription>
              Configure the AI provider used for market analysis. For desktop installations,
              set your API credentials here.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Current Status */}
            {llmLoading ? (
              <Skeleton className="h-12 w-full" />
            ) : (
              <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-muted/50 border border-border/50">
                <div className={`h-2 w-2 rounded-full ${getProviderStatusColor()}`} />
                <span className="text-sm font-medium">
                  {llmStatus?.active_provider_display || 'Unknown'}
                </span>
                <Badge variant="outline" className="ml-auto text-xs">
                  {llmStatus?.model || 'N/A'}
                </Badge>
              </div>
            )}

            {/* Env override warning */}
            {llmStatus?.env_override && (
              <div className="flex items-start gap-2 px-4 py-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-sm">
                <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5 shrink-0" />
                <span className="text-muted-foreground">
                  Some settings are configured via <code className="text-xs bg-muted px-1 py-0.5 rounded">.env</code> file
                  and take priority over values set here.
                </span>
              </div>
            )}

            {/* Provider Selector */}
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select
                value={selectedProvider}
                onValueChange={(v) => updateField('llm_provider', v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select provider" />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      <span>{opt.label}</span>
                      <span className="ml-2 text-xs text-muted-foreground">{opt.description}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Provider-specific fields */}
            {(selectedProvider === 'anthropic_api' || selectedProvider === 'auto') && (
              <div className="space-y-2">
                <Label>API Key</Label>
                <Input
                  type="password"
                  placeholder={llmStatus?.anthropic_api_key || 'sk-ant-...'}
                  value={llmForm.anthropic_api_key || ''}
                  onChange={(e) => updateField('anthropic_api_key', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Your Anthropic API key (starts with sk-ant-).
                </p>
              </div>
            )}

            {(selectedProvider === 'proxy') && (
              <>
                <div className="space-y-2">
                  <Label>Auth Token</Label>
                  <Input
                    type="password"
                    placeholder={llmStatus?.anthropic_auth_token || 'Token or API key'}
                    value={llmForm.anthropic_auth_token || ''}
                    onChange={(e) => updateField('anthropic_auth_token', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Base URL</Label>
                  <Input
                    placeholder="https://api.z.ai/api/anthropic"
                    value={llmForm.anthropic_base_url || ''}
                    onChange={(e) => updateField('anthropic_base_url', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Timeout (ms)</Label>
                  <Input
                    type="number"
                    placeholder="30000"
                    value={llmForm.api_timeout_ms || ''}
                    onChange={(e) => updateField('api_timeout_ms', e.target.value ? parseInt(e.target.value) : null)}
                  />
                </div>
              </>
            )}

            {selectedProvider === 'ollama' && (
              <div className="space-y-2">
                <Label>Base URL</Label>
                <Input
                  placeholder="http://localhost:11434"
                  value={llmForm.anthropic_base_url || ''}
                  onChange={(e) => updateField('anthropic_base_url', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Default: http://localhost:11434
                </p>
              </div>
            )}

            {selectedProvider === 'bedrock' && (
              <div className="space-y-2">
                <Label>AWS Region</Label>
                <Input
                  placeholder="us-east-1"
                  value={llmForm.aws_region || ''}
                  onChange={(e) => updateField('aws_region', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  AWS credentials must be configured separately (via AWS CLI or environment).
                </p>
              </div>
            )}

            {selectedProvider === 'vertex' && (
              <>
                <div className="space-y-2">
                  <Label>Project ID</Label>
                  <Input
                    placeholder="my-gcp-project"
                    value={llmForm.vertex_project || ''}
                    onChange={(e) => updateField('vertex_project', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Region</Label>
                  <Input
                    placeholder="us-central1"
                    value={llmForm.vertex_region || ''}
                    onChange={(e) => updateField('vertex_region', e.target.value)}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  GCP credentials must be configured separately (via gcloud CLI or service account).
                </p>
              </>
            )}

            {selectedProvider === 'azure' && (
              <p className="text-sm text-muted-foreground px-1">
                Azure AI Foundry credentials are configured via environment variables.
                Ensure your Azure credentials are available.
              </p>
            )}

            {selectedProvider === 'subscription' && (
              <div className="flex items-start gap-2 px-4 py-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-sm">
                <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5 shrink-0" />
                <span className="text-muted-foreground">
                  Claude Code subscription auth relies on a local Claude Code login and is
                  <strong> not recommended</strong> for distributed or production deployments.
                  See Anthropic TOS for usage limitations.
                </span>
              </div>
            )}

            {/* Model override */}
            <div className="space-y-2">
              <Label>Model</Label>
              <Input
                placeholder="claude-sonnet-4-20250514"
                value={llmForm.anthropic_model || ''}
                onChange={(e) => updateField('anthropic_model', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Override the default model. Leave empty to use the default.
              </p>
            </div>

            {/* Test result */}
            {testResult && (
              <div className={`flex items-start gap-2 px-4 py-3 rounded-lg text-sm ${
                testResult.success
                  ? 'bg-green-500/10 border border-green-500/30'
                  : 'bg-red-500/10 border border-red-500/30'
              }`}>
                {testResult.success ? (
                  <Check className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                )}
                <div>
                  <p className="font-medium">{testResult.success ? 'Connection successful' : 'Connection failed'}</p>
                  <p className="text-muted-foreground mt-1">{testResult.message}</p>
                  {testResult.response_preview && (
                    <p className="text-xs text-muted-foreground mt-1 italic">
                      &quot;{testResult.response_preview}&quot;
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-3 pt-2">
              <Button
                onClick={handleSaveLLM}
                disabled={llmSaving}
              >
                {llmSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : null}
                Save Settings
              </Button>
              <Button
                variant="outline"
                onClick={handleTestConnection}
                disabled={llmTesting}
              >
                {llmTesting ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Zap className="h-4 w-4 mr-2" />
                )}
                Test Connection
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Connection status when there's an error */}
        {(error || llmError) && <ConnectionError error={error || llmError!} />}

        {/* Watchlist Card */}
        <Card>
          <CardHeader>
            <CardTitle>Watchlist</CardTitle>
            <CardDescription>
              Manage the stock symbols to track and refresh.
              {watchlist?.last_refresh && (
                <span className="block mt-1 text-xs">
                  Last refreshed: {new Date(watchlist.last_refresh).toLocaleString()}
                </span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-full" />
                <div className="flex gap-2">
                  <Skeleton className="h-7 w-16" />
                  <Skeleton className="h-7 w-16" />
                  <Skeleton className="h-7 w-16" />
                </div>
              </div>
            ) : (
              <>
                <div className="flex gap-2 mb-4">
                  <Input
                    placeholder="Enter symbol (e.g., AAPL)"
                    value={newSymbol}
                    onChange={(e) => setNewSymbol(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !isPending && addSymbol()}
                    disabled={isPending}
                  />
                  <Button onClick={addSymbol} variant="outline" disabled={isPending}>
                    {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  </Button>
                </div>

                <div className="flex flex-wrap gap-2">
                  {watchlist?.symbols && watchlist.symbols.length > 0 ? (
                    watchlist.symbols.map((symbol) => (
                      <Badge key={symbol} variant="secondary" className="pl-3 pr-1 py-1">
                        {symbol}
                        <button
                          onClick={() => removeSymbol(symbol)}
                          disabled={isPending}
                          className="ml-2 hover:bg-destructive/20 rounded-full p-0.5 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No symbols in watchlist. Add one above to get started.
                    </p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
