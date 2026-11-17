import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import type { APIRoute } from 'astro';
import { getPublishedPosts } from '../../lib/posts';
import { SITE_TITLE, SITE_DESCRIPTION } from '../../config';

const fontDir = resolve(process.cwd(), 'src/assets/fonts');
const fonts = [
  { name: 'Liberation Sans', data: readFileSync(resolve(fontDir, 'LiberationSans-Regular.ttf')), weight: 400 as const, style: 'normal' as const },
  { name: 'Liberation Sans', data: readFileSync(resolve(fontDir, 'LiberationSans-Bold.ttf')), weight: 700 as const, style: 'normal' as const },
];

export async function getStaticPaths() {
  const posts = await getPublishedPosts();
  return [
    { params: { slug: 'default' }, props: { title: SITE_TITLE, subtitle: SITE_DESCRIPTION } },
    ...posts.map((p) => ({
      params: { slug: p.slug },
      props: { title: p.data.title, subtitle: p.data.tags.map((t) => `#${t}`).join('  ') },
    })),
  ];
}

export const GET: APIRoute = async ({ props }) => {
  const { title, subtitle } = props as { title: string; subtitle: string };
  const tree = {
    type: 'div',
    props: {
      style: {
        width: '100%', height: '100%', display: 'flex', flexDirection: 'column',
        justifyContent: 'space-between', padding: '72px', background: '#0b1220', color: '#f1f5f9',
        fontFamily: 'Liberation Sans',
      },
      children: [
        { type: 'div', props: { style: { fontSize: 30, color: '#38bdf8', fontWeight: 700 }, children: SITE_TITLE } },
        { type: 'div', props: { style: { fontSize: title.length > 70 ? 54 : 68, fontWeight: 700, lineHeight: 1.15 }, children: title } },
        { type: 'div', props: { style: { fontSize: 28, color: '#94a3b8' }, children: subtitle } },
      ],
    },
  };
  const svg = await satori(tree as never, { width: 1200, height: 630, fonts });
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: 1200 } }).render().asPng();
  return new Response(new Uint8Array(png), { headers: { 'Content-Type': 'image/png' } });
};
