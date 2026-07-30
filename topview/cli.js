#!/usr/bin/env node
/**
 * cli.js — Tạo ảnh / video bằng TopView từ dòng lệnh.
 *
 * Cách dùng:
 *   export TOPVIEW_API_KEY="khoá-của-bạn"
 *
 *   node topview/cli.js anh   "một ly cà phê trên bàn gỗ" -o anh.png
 *   node topview/cli.js video "quảng cáo cà phê 10 giây"  -o video.mp4
 *   node topview/cli.js video "sản phẩm xoay tròn" --anh anh1.png,anh2.png -o v.mp4
 *
 * Tuỳ chọn:
 *   -o, --out FILE       Tên file kết quả (bắt buộc).
 *   -n, --so-luong N     Số ảnh cần tạo (chỉ cho lệnh "anh", mặc định 1).
 *   -k, --khung TỈ_LỆ    Tỉ lệ khung: 1:1, 16:9, 9:16... (mặc định 1:1 cho ảnh, 9:16 cho video).
 *   -d, --thoi-luong N   Độ dài video mong muốn, giây.
 *       --anh A,B        Danh sách URL ảnh đầu vào để dựng video.
 *   -h, --help           Hiện trợ giúp.
 *
 * File tạo ra dùng thẳng được với các script ffmpeg trong repo, ví dụ:
 *   node topview/cli.js video "cảnh 1" -o c1.mp4
 *   node topview/cli.js video "cảnh 2" -o c2.mp4
 *   ./chuyen-canh.sh ket-qua.mp4 c1.mp4 c2.mp4
 */

'use strict';

const { TopViewClient, TopViewError } = require('./client');

function help(code = 0) {
  const src = require('fs').readFileSync(__filename, 'utf8');
  const block = src.split('*/')[0].split('\n')
    .filter((l) => l.startsWith(' *'))
    .map((l) => l.replace(/^ \* ?/, ''))
    .join('\n');
  console.log(block);
  process.exit(code);
}

function parseArgs(argv) {
  const opts = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '-o': case '--out':        opts.out = argv[++i]; break;
      case '-n': case '--so-luong':   opts.soLuong = parseInt(argv[++i], 10); break;
      case '-k': case '--khung':      opts.khung = argv[++i]; break;
      case '-d': case '--thoi-luong': opts.thoiLuong = parseInt(argv[++i], 10); break;
      case '--anh':                   opts.anh = argv[++i].split(',').map((s) => s.trim()).filter(Boolean); break;
      case '-h': case '--help':       help(0); break;
      default:
        if (a.startsWith('-')) {
          console.error(`Không hiểu tuỳ chọn: ${a}`);
          help(1);
        }
        opts.positional.push(a);
    }
  }
  return opts;
}

// Hiển thị tiến độ cho người dùng biết máy vẫn đang chạy.
function progressHandler({ phase, taskId, label, status, progress, elapsedMs, path: p }) {
  if (phase === 'submitted') {
    console.log(`==> Đã gửi yêu cầu ${label}. Mã tác vụ: ${taskId}`);
  } else if (phase === 'running') {
    const giay = Math.round((elapsedMs || 0) / 1000);
    const pct = progress !== undefined ? ` ${progress}%` : '';
    process.stdout.write(`\r    Đang xử lý... ${status || ''}${pct} (${giay}s)   `);
  } else if (phase === 'done') {
    process.stdout.write('\n');
    console.log(`==> Xong! Đang tải file về...`);
  } else if (phase === 'downloaded') {
    console.log(`==> Đã lưu: ${p}`);
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const [lenh, ...moTaParts] = opts.positional;
  const moTa = moTaParts.join(' ');

  if (!lenh) help(0);
  if (!['anh', 'image', 'video'].includes(lenh)) {
    console.error(`Lệnh không hợp lệ: "${lenh}". Dùng "anh" hoặc "video".`);
    help(1);
  }
  if (!opts.out) {
    console.error('Thiếu tên file kết quả. Thêm: -o ten-file.png (hoặc .mp4)');
    help(1);
  }
  if (!moTa && !(opts.anh && opts.anh.length)) {
    console.error('Thiếu mô tả nội dung cần tạo.');
    help(1);
  }

  const tv = new TopViewClient({ onProgress: progressHandler });

  let ketQua;
  if (lenh === 'video') {
    console.log(`==> Tạo video: "${moTa || '(từ ảnh đầu vào)'}"`);
    ketQua = await tv.generateVideo({
      prompt: moTa || undefined,
      imageUrls: opts.anh,
      aspectRatio: opts.khung || '9:16',
      duration: opts.thoiLuong,
    });
  } else {
    console.log(`==> Tạo ảnh: "${moTa}"`);
    ketQua = await tv.generateImage({
      prompt: moTa,
      aspectRatio: opts.khung || '1:1',
      imageCount: opts.soLuong || 1,
    });
  }

  await tv.downloadTo(ketQua.url, opts.out);
}

main().catch((err) => {
  process.stdout.write('\n');
  if (err instanceof TopViewError) {
    console.error(`Lỗi: ${err.message}`);
    if (err.taskId) console.error(`      (mã tác vụ: ${err.taskId})`);
  } else {
    console.error(`Lỗi không mong đợi: ${err && err.stack ? err.stack : err}`);
  }
  process.exit(1);
});
