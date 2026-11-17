import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { getPublishedPosts } from '../lib/posts';
import { canonicalUrl } from '../lib/urls';
import { SITE_TITLE, SITE_DESCRIPTION, SITE_URL } from '../config';

export async function GET(_context: APIContext) {
  const posts = await getPublishedPosts();
  return rss({
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    site: SITE_URL,
    items: posts.map((p) => ({
      title: p.data.title,
      description: p.data.description,
      pubDate: p.data.date,
      link: canonicalUrl(p.slug),
      categories: p.data.tags,
    })),
  });
}
