import { parseComponent } from 'vue-template-compiler';
import { describe, expect, it } from 'vitest';
import source from '../src/views/roleConfig.vue?raw';

// The unit-test runner has no Vue SFC plugin. Load the real component's script
// with its imports stripped; applyTemplateData only touches `this.form`.
const script = parseComponent(source).script.content
  .replace(/^import .+?;.*$/gm, '')
  .replace('export default', 'return');
const deps = [
  'Api', 'getServiceUrl', 'RequestService', 'FunctionDialog',
  'ContextProviderDialog', 'TtsAdvancedSettings', 'AgentSnapshotDialog',
  'HeaderBar', 'i18n', 'featureManager', 'VersionFooter',
];
const component = new Function(...deps, script)(...deps.map(() => ({})));

function makeVm() {
  return {
    form: {
      agentName: '英语老师',
      systemPrompt: '[角色设定] 英语老师',
      summaryMemory: '',
      langCode: 'zh',
      chatHistoryConf: 0,
      ttsVoiceId: 'TTS_CustomTTS0000',
      model: {
        ttsModelId: 'TTS_CustomTTS',
        vadModelId: 'VAD_SileroVAD',
        asrModelId: 'ASR_FunASR',
        llmModelId: 'LLM_DeepSeekLLM',
        slmModelId: 'LLM_DeepSeekLLM',
        vllmModelId: 'VLLM_ChatGLMVLLM',
        memModelId: 'Memory_nomem',
        intentModelId: 'Intent_function_call',
      },
    },
    selectedLanguage: '中文',
    fetchVoiceOptions: () => {
      throw new Error('applying a role template must not refetch/repick voices');
    },
  };
}

// A template as returned by GET /agent/template without any pruning.
const template = {
  agentName: '湾湾小何',
  systemPrompt: '[角色设定] 湾湾小何',
  langCode: 'zh',
  chatHistoryConf: 0,
  ttsModelId: 'TTS_EdgeTTS',
  ttsVoiceId: 'TTS_EdgeTTS0001',
  ttsLanguage: '普通话',
  vadModelId: 'VAD_SileroVAD',
  asrModelId: 'ASR_FunASR',
  llmModelId: 'LLM_ChatGLMLLM',
  vllmModelId: 'VLLM_ChatGLMVLLM',
  memModelId: 'Memory_nomem',
  intentModelId: 'Intent_function_call',
};

describe('applying a role template', () => {
  it('applies the role text', () => {
    const vm = makeVm();
    component.methods.applyTemplateData.call(vm, template);

    expect(vm.form.agentName).toBe('湾湾小何');
    expect(vm.form.systemPrompt).toBe('[角色设定] 湾湾小何');
  });

  it('keeps the model and TTS wiring the user configured', () => {
    const vm = makeVm();
    component.methods.applyTemplateData.call(vm, template);

    expect(vm.form.model.ttsModelId).toBe('TTS_CustomTTS');
    expect(vm.form.model.llmModelId).toBe('LLM_DeepSeekLLM');
    expect(vm.form.model.vllmModelId).toBe('VLLM_ChatGLMVLLM');
    expect(vm.form.model.intentModelId).toBe('Intent_function_call');
    expect(vm.form.ttsVoiceId).toBe('TTS_CustomTTS0000');
    expect(vm.selectedLanguage).toBe('中文');
  });
});
