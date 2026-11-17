import { getCollection, type CollectionEntry } from 'astro:content';
import { slugFromId } from './urls';

export type Post = CollectionEntry<'posts'> & { slug: string };

/**
 * The only way pages read posts. Drafts are filtered here so a
 * `draft: true` post can never reach a page, the RSS feed, tags or the sitemap.
 */
export async function getPublishedPosts(): Promise<Post[]> {
  const entries = await getCollection('posts', ({ data }) => !data.draft);
  return entries
    .map((e) => ({ ...e, slug: slugFromId(e.id) }))
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());
}

export async function getTags(): Promise<Map<string, Post[]>> {
  const map = new Map<string, Post[]>();
  for (const post of await getPublishedPosts()) {
    for (const tag of post.data.tags) {
      const key = tag.toLowerCase();
      map.set(key, [...(map.get(key) ?? []), post]);
    }
  }
  return map;
}

export function formatDate(d: Date): string {
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
}
