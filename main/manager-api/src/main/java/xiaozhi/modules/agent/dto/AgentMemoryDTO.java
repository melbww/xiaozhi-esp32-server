package xiaozhi.modules.agent.dto;

import java.io.Serializable;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 智能体记忆更新DTO
 */
@Data
@Schema(description = "智能体记忆更新对象")
public class AgentMemoryDTO implements Serializable {
    private static final long serialVersionUID = 1L;

    @Schema(description = "总结记忆", example = "Build a growable, dynamic memory network that keeps key information within limited space while intelligently maintaining the evolution trail of that information\n" +
            "Based on the conversation record, summarize the user's important information so that future conversations can be more personalized", requiredMode = Schema.RequiredMode.NOT_REQUIRED)
    private String summaryMemory;
}
