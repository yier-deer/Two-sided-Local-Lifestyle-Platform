import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const assets = { hotpot: 'photo-1544025162-d76694265947', coffee: 'photo-1511920170033-f8396924c348', dining: 'photo-1504674900247-0877df9cc836', cinema: 'photo-1489599849927-2ee91cede3ba', bakery: 'photo-1509440159596-0249088772ff', restaurant: 'photo-1517248135467-4c7edcad34c4', cafe: 'photo-1501339847302-ac426a4a7cbb' }
const directory = new URL('../apps/web/public/images/', import.meta.url)
await mkdir(directory, { recursive: true })
await Promise.all(Object.entries(assets).map(async ([name, photo]) => {
  const response = await fetch(`https://images.unsplash.com/${photo}?auto=format&fit=crop&w=1200&q=85`, { signal: AbortSignal.timeout(30000) })
  if (!response.ok) throw new Error(`${name}: ${response.status}`)
  const bytes = Buffer.from(await response.arrayBuffer())
  await writeFile(new URL(`${name}.jpg`, directory), bytes)
  console.log(`${name}.jpg: ${bytes.length} bytes`)
}))
await writeFile(new URL('CREDITS.md', directory), '# 展示图片\n\n这些是用于本地答辩界面配图的 Unsplash 展示素材，并非对应店铺的实拍照片。\n\n' + Object.entries(assets).map(([name, photo]) => `- ${name}.jpg: https://images.unsplash.com/${photo}`).join('\n') + '\n\nUnsplash license: https://unsplash.com/license\n')
console.log(`Saved to ${fileURLToPath(directory)}`)
