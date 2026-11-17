import siteConfig from '../site.config.json';

export const SITE_URL: string = siteConfig.siteUrl.replace(/\/+$/, '');
export const SITE_TITLE: string = siteConfig.title;
export const SITE_DESCRIPTION: string = siteConfig.description;
export const AUTHOR: string = siteConfig.author;
export const GITHUB_USER: string = siteConfig.githubUser;
