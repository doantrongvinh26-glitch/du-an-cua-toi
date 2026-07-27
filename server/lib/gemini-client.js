const MODEL = 'gemini-flash-latest';
const API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';

const SCENE_SCHEMA = {
  type: 'object',
  properties: {
    scenes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          index: { type: 'integer' },
          summary: { type: 'string' },
          veo3Prompt: { type: 'string' },
        },
        required: ['index', 'summary', 'veo3Prompt'],
      },
    },
  },
  required: ['scenes'],
};

const SYSTEM_INSTRUCTION = `Bạn là chuyên gia viết prompt cho Veo3 (mô hình tạo video AI của Google).
Nhiệm vụ: nhận một kịch bản (tiếng Việt) và chia thành các cảnh quay kế tiếp nhau, mỗi cảnh dài 4-8 giây (giới hạn độ dài một lần render của Veo3).
Với mỗi cảnh, viết MỘT prompt bằng tiếng Anh, chi tiết và mang tính điện ảnh: chủ thể, hành động, bối cảnh, góc máy/chuyển động camera, ánh sáng, phong cách hình ảnh, tâm trạng.
QUAN TRỌNG để ghép các cảnh lại mượt mà bằng crossfade: giữ nhất quán ngoại hình nhân vật, trang phục, bối cảnh, tông màu ánh sáng xuyên suốt các cảnh liền kề trừ khi kịch bản yêu cầu thay đổi rõ ràng; mô tả tư thế/vị trí/hướng nhìn lúc kết thúc của một cảnh sao cho khớp với lúc bắt đầu của cảnh kế tiếp.
Trả lời đúng theo JSON schema đã cho, không thêm chữ nào khác ngoài JSON.`;

async function generateScenePrompts(script, apiKey) {
  const url = `${API_BASE}/${MODEL}:generateContent?key=${encodeURIComponent(apiKey)}`;
  const body = {
    systemInstruction: { parts: [{ text: SYSTEM_INSTRUCTION }] },
    contents: [{ role: 'user', parts: [{ text: `Kịch bản:\n${script}` }] }],
    generationConfig: {
      responseMimeType: 'application/json',
      responseSchema: SCENE_SCHEMA,
    },
  };

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    throw new Error(`Gemini API lỗi (${res.status}): ${errText.slice(0, 300)}`);
  }

  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) {
    throw new Error('Gemini API không trả về nội dung hợp lệ.');
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error('Không đọc được JSON trả về từ Gemini.');
  }

  if (!parsed || !Array.isArray(parsed.scenes)) {
    throw new Error('Định dạng phản hồi không đúng (thiếu scenes).');
  }

  return parsed.scenes;
}

module.exports = { generateScenePrompts };
