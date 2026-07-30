/**
 * config.js — Cấu hình kết nối TopView API.
 *
 * QUAN TRỌNG: Trang tài liệu docs.topview.ai chặn truy cập tự động, nên các
 * giá trị mặc định dưới đây dựa trên mô tả API công khai của TopView và CẦN
 * ĐƯỢC ĐỐI CHIẾU MỘT LẦN với tài liệu trong tài khoản của bạn:
 *
 *   1. Đăng nhập https://www.topview.ai/api-settings  -> lấy API key.
 *   2. Mở https://docs.topview.ai  -> đối chiếu baseUrl, tên header xác thực
 *      và đường dẫn endpoint bên dưới. Sửa lại nếu khác.
 *
 * Mọi thứ phụ thuộc nhà cung cấp đều nằm gọn trong file này — đổi ở đây là
 * cả module chạy theo, không phải sửa client.js.
 */

'use strict';

const config = {
  // Địa chỉ gốc của API.
  baseUrl: process.env.TOPVIEW_BASE_URL || 'https://api.topview.ai',

  // API key: KHÔNG hardcode vào mã nguồn — đặt trong biến môi trường.
  apiKey: process.env.TOPVIEW_API_KEY || '',

  /**
   * Tên header gửi API key. TopView dùng header riêng chứ không phải
   * Bearer chuẩn; nếu tài khoản bạn dùng kiểu khác thì sửa hàm này.
   */
  authHeaders(apiKey) {
    return {
      'Authorization': `Bearer ${apiKey}`,
      'X-API-KEY': apiKey,
    };
  },

  // Đường dẫn endpoint. Sửa cho khớp tài liệu nếu cần.
  endpoints: {
    // Tạo ảnh từ văn bản.
    imageSubmit: '/v1/image/task/submit',
    // Tạo video từ ảnh/kịch bản (materials2video).
    videoSubmit: '/v1/materials2video/task/submit',
    // Tra trạng thái tác vụ. {taskId} sẽ được thay bằng id thật.
    taskQuery: '/v1/task/query?taskId={taskId}',
  },

  // Thời gian chờ khi hỏi kết quả (tác vụ tạo ảnh/video chạy bất đồng bộ).
  polling: {
    intervalMs: 5000,      // 5 giây hỏi lại một lần
    timeoutMs: 15 * 60000, // bỏ cuộc sau 15 phút
  },

  // Số lần thử lại khi lỗi mạng tạm thời.
  retry: {
    attempts: 3,
    backoffMs: 2000, // 2s, 4s, 8s
  },
};

module.exports = config;
