'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { Plus, X, Loader2, Settings2, Cpu, Zap, AlertTriangle, Check, RotateCcw } from 'lucide-react';
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
import { useLLMSettings, useUpdateLLMSettings, useTestLLMConnection, useResetLLMSettings } from '@/lib/hooks/use-llm-settings';
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
  const { mutate: updateLLM } = useUpdateLLMSettings();
  const { mutate: testConnection, isPending: llmTesting, data: testResult, reset: resetTest } = useTestLLMConnection();
  const { mutate: resetLLM, isPending: llmResetting } = useResetLLMSettings();

  // Form state for LLM settings -- populated from server data via useEffect
  const [llmForm, setLLMForm] = useState<LLMProviderConfig>({ llm_provider: 'auto' });

  // Auto-save state
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const userHasEdited = useRef(false);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedFadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // When server data loads (or changes), populate the form with non-sensitive fields.
  // Sensitive fields (api_key, auth_token) are left empty since the server returns masked values;
  // the form shows placeholder text indicating a value is saved.
  useEffect(() => {
    if (!llmStatus) return;
    setLLMForm(prev => ({
      // Keep any user-edited values that have been explicitly typed into the form,
      // but provide server values as the base for anything not yet overridden.
      llm_provider: llmStatus.configured_provider ?? 'auto',
      anthropic_base_url: llmStatus.anthropic_base_url ?? undefined,
      api_timeout_ms: llmStatus.api_timeout_ms != null ? Number(llmStatus.api_timeout_ms) : undefined,
      anthropic_model: llmStatus.model ?? undefined,
      aws_region: llmStatus.aws_region ?? undefined,
      vertex_project: llmStatus.vertex_project ?? undefined,
      vertex_region: llmStatus.vertex_region ?? undefined,
      // Sensitive fields: leave empty (don't populate with masked server values)
      // They remain whatever the user has typed, or empty if untouched.
      anthropic_api_key: prev.anthropic_api_key || undefined,
      anthropic_auth_token: prev.anthropic_auth_token || undefined,
    }));
  }, [llmStatus]);

  const selectedProvider = llmForm.llm_provider || 'auto';

  const updateField = useCallback((field: keyof LLMProviderConfig, value: string | number | null) => {
    resetTest();
    userHasEdited.current = true;
    setLLMForm(prev => ({ ...prev, [field]: value || undefined }));
  }, [resetTest]);

  // Build the config object from current form state
  const buildConfig = useCallback((): LLMProviderConfig => {
    const provider = llmForm.llm_provider || 'auto';
    const config: LLMProviderConfig = {
      llm_provider: provider,
      anthropic_model: llmForm.anthropic_model || undefined,
    };

    if (provider === 'anthropic_api' || provider === 'auto') {
      if (llmForm.anthropic_api_key) config.anthropic_api_key = llmForm.anthropic_api_key;
    }
    if (provider === 'proxy' || provider === 'ollama') {
      if (llmForm.anthropic_auth_token) config.anthropic_auth_token = llmForm.anthropic_auth_token;
      config.anthropic_base_url = llmForm.anthropic_base_url || undefined;
      if (llmForm.api_timeout_ms) config.api_timeout_ms = llmForm.api_timeout_ms;
    }
    if (provider === 'ollama') {
      config.anthropic_base_url = llmForm.anthropic_base_url || 'http://localhost:11434';
    }
    if (provider === 'bedrock') {
      config.aws_region = llmForm.aws_region || undefined;
    }
    if (provider === 'vertex') {
      config.vertex_project = llmForm.vertex_project || undefined;
      config.vertex_region = llmForm.vertex_region || undefined;
    }

    return config;
  }, [llmForm]);

  // Check if form has meaningful content worth saving (not just defaults with no credentials)
  const hasSubstantiveContent = useCallback((): boolean => {
    const provider = llmForm.llm_provider || 'auto';
    // If provider is not auto, that's a deliberate choice worth saving
    if (provider !== 'auto') return true;
    // If any credentials are filled in, save
    if (llmForm.anthropic_api_key || llmForm.anthropic_auth_token) return true;
    // If model is overridden, save
    if (llmForm.anthropic_model) return true;
    // If any cloud/proxy settings are filled in, save
    if (llmForm.anthropic_base_url || llmForm.aws_region || llmForm.vertex_project || llmForm.vertex_region) return true;
    if (llmForm.api_timeout_ms) return true;
    return false;
  }, [llmForm]);

  // Debounced auto-save: watches form state and saves after 1s of inactivity
  useEffect(() => {
    // Don't auto-save if user hasn't edited, or if still loading, or form is empty/default
    if (!userHasEdited.current || llmLoading) return;
    if (!hasSubstantiveContent()) return;

    // Clear any existing debounce timer
    if (debounceTimer.current) clearTimeout(debounceTimer.current);

    debounceTimer.current = setTimeout(() => {
      const config = buildConfig();
      setSaveStatus('saving');
      setSaveError(null);
      if (savedFadeTimer.current) clearTimeout(savedFadeTimer.current);

      updateLLM(config, {
        onSuccess: () => {
          setSaveStatus('saved');
          // Clear sensitive fields from local form state so the useEffect
          // repopulates non-sensitive fields from the refreshed server data.
          setLLMForm(prev => ({
            ...prev,
            anthropic_api_key: undefined,
            anthropic_auth_token: undefined,
          }));
          // Fade back to idle after 3 seconds
          savedFadeTimer.current = setTimeout(() => setSaveStatus('idle'), 3000);
        },
        onError: (err) => {
          setSaveStatus('error');
          setSaveError(err.message);
        },
      });
    }, 1000);

    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [llmForm, llmLoading, buildConfig, hasSubstantiveContent, updateLLM]);

  const handleTestConnection = () => {
    testConnection(
      {
        provider: selectedProvider,
        auth_token: llmForm.anthropic_auth_token || null,
        base_url: llmForm.anthropic_base_url || null,
        api_key: llmForm.anthropic_api_key || null,
        model: llmForm.anthropic_model || null,
        timeout_ms: llmForm.api_timeout_ms || null,
      },
      {
        onSuccess: (result) => {
          if (result.success) {
            toast.success('Connection test passed');
          } else {
            toast.error(`Connection test failed: ${result.message}`);
          }
        },
        onError: (err) => toast.error(`Test error: ${err.message}`),
      },
    );
  };

  const handleResetLLM = () => {
    if (!confirm('Reset LLM settings? This will clear all saved credentials and revert to Claude Code subscription.')) {
      return;
    }
    resetTest();
    resetLLM(undefined, {
      onSuccess: () => {
        // Reset local form state to defaults
        userHasEdited.current = false;
        setLLMForm({ llm_provider: 'auto' });
        setSaveStatus('idle');
        setSaveError(null);
        toast.success('LLM settings reset to defaults');
      },
      onError: (err) => toast.error(`Reset failed: ${err.message}`),
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
              {/* Auto-save status indicator */}
              {saveStatus === 'saving' && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Saving...
                </span>
              )}
              {saveStatus === 'saved' && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400 animate-in fade-in duration-300">
                  <Check className="h-3 w-3" />
                  Saved
                </span>
              )}
              {saveStatus === 'error' && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-red-500" title={saveError || undefined}>
                  <AlertTriangle className="h-3 w-3" />
                  Error saving
                </span>
              )}
            </div>
            <CardDescription>
              Configure the AI provider used for market analysis. For desktop installations,
              set your API credentials here.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {llmLoading ? (
              /* Show skeletons for the entire form while loading so fields
                 are never rendered empty before server data arrives. */
              <div className="space-y-6">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-1/2" />
              </div>
            ) : (
              <>
                {/* Current Status */}
                <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-muted/50 border border-border/50">
                  <div className={`h-2 w-2 rounded-full ${getProviderStatusColor()}`} />
                  <span className="text-sm font-medium">
                    {llmStatus?.active_provider_display || 'Unknown'}
                  </span>
                  <Badge variant="outline" className="ml-auto text-xs">
                    {llmStatus?.model || 'N/A'}
                  </Badge>
                </div>

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
                      placeholder={llmStatus?.anthropic_api_key ? `Saved (${llmStatus.anthropic_api_key})` : 'sk-ant-...'}
                      value={llmForm.anthropic_api_key || ''}
                      onChange={(e) => updateField('anthropic_api_key', e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Your Anthropic API key (starts with sk-ant-).
                      {llmStatus?.anthropic_api_key && !llmForm.anthropic_api_key && (
                        <span className="ml-1 text-green-600 dark:text-green-400">Key saved on server.</span>
                      )}
                    </p>
                  </div>
                )}

                {(selectedProvider === 'proxy') && (
                  <>
                    <div className="space-y-2">
                      <Label>Auth Token</Label>
                      <Input
                        type="password"
                        placeholder={llmStatus?.anthropic_auth_token ? `Saved (${llmStatus.anthropic_auth_token})` : 'Token or API key'}
                        value={llmForm.anthropic_auth_token || ''}
                        onChange={(e) => updateField('anthropic_auth_token', e.target.value)}
                      />
                      {llmStatus?.anthropic_auth_token && !llmForm.anthropic_auth_token && (
                        <p className="text-xs text-green-600 dark:text-green-400">Token saved on server.</p>
                      )}
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
                        value={llmForm.api_timeout_ms ?? ''}
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

                {/* Test Connection + Reset buttons */}
                <div className="flex gap-3 pt-2">
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
                  <Button
                    variant="outline"
                    onClick={handleResetLLM}
                    disabled={llmResetting}
                    className="text-destructive border-destructive/50 hover:bg-destructive/10"
                  >
                    {llmResetting ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <RotateCcw className="h-4 w-4 mr-2" />
                    )}
                    Reset to Defaults
                  </Button>
                </div>
              </>
            )}
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
