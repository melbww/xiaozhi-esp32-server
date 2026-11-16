package xiaozhi.modules.agent.dto;

import java.util.Date;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import xiaozhi.modules.agent.dto.AgentTagDTO;

/**
 * 智能体数据传输对象
 * 用于在服务层和控制器层之间传递智能体相关的数据
 */
@Data
@Schema(description = "智能体对象")
public class AgentDTO {
    @Schema(description = "智能体编码", example = "AGT_1234567890")
    private String id;

    @Schema(description = "智能体名称", example = "客服助手")
    private String agentName;

    @Schema(description = "语音合成模型名称", example = "tts_model_01")
    private String ttsModelName;

    @Schema(description = "音色名称", example = "voice_01")
    private String ttsVoiceName;

    @Schema(description = "大语言模型名称", example = "llm_model_01")
    private String llmModelName;

    @Schema(description = "视觉模型名称", example = "vllm_model_01")
    private String vllmModelName;

    @Schema(description = "记忆模型ID", example = "mem_model_01")
    private String memModelId;

    @Schema(description = "角色设定参数", example = "You are a professional customer service assistant who answers user questions and provides help")
    private String systemPrompt;

    @Schema(description = "总结记忆", example = "Build a growable, dynamic memory network that keeps key information within limited space while intelligently maintaining the evolution trail of that information\n" +
            "Based on the conversation record, summarize the user's important information so that future conversations can be more personalized", requiredMode = Schema.RequiredMode.NOT_REQUIRED)
    private String summaryMemory;

    @Schema(description = "最后连接时间", example = "2024-03-20 10:00:00")
    private Date lastConnectedAt;

    @Schema(description = "设备数量", example = "10")
    private Integer deviceCount;

    @Schema(description = "标签列表")
    private List<AgentTagDTO> tags;
}
