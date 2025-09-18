import hyphae
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import re
from urllib.parse import quote
import feedparser
import time
import traceback
from hyphae.tools.respond_to_user import RespondToUserReturnType
from perplexity import PerplexitySearcher
import hyphae.hooks as hooks

class ArxivApp:
    def __init__(self):
        self.selected_paper = None
        self.paper_content = None
        
    def has_paper_selected(self) -> bool:
        """Check if a paper is currently selected for analysis"""
        return self.selected_paper is not None
        
    @hyphae.tool("Search for papers on a specific topic or field", icon="magnifyingglass")
    @hyphae.args(
        query="The search query (can be a topic, keywords, or specific paper title)",
        max_results="Maximum number of results to return (default: 10)"
    )
    def SearchPapers(self, query: str, max_results: int = 10) -> str:
        # ArXiv API search
        base_url = "http://export.arxiv.org/api/query"
        search_query = f"search_query=all:{quote(query)}"
        params = f"{search_query}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        
        url = f"{base_url}?{params}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            # Parse the Atom feed
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"No papers found for query: {query}"
            
            results = []
            for i, entry in enumerate(feed.entries, 1):
                # Extract information
                title = entry.title.replace('\n', ' ').strip()
                authors = [author.name for author in entry.authors] if hasattr(entry, 'authors') else []
                author_str = ", ".join(authors[:3])  # Show first 3 authors
                if len(authors) > 3:
                    author_str += " et al."
                
                # Extract ArXiv ID from the entry link
                arxiv_id = entry.id.split('/')[-1]
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                
                # Extract abstract
                summary = entry.summary.replace('\n', ' ').strip()
                
                # Extract published date
                published = entry.published[:10] if hasattr(entry, 'published') else "Unknown"
                
                # Extract categories
                categories = []
                if hasattr(entry, 'tags'):
                    categories = [tag.term for tag in entry.tags]
                category_str = ", ".join(categories[:3])
                
                paper_info = f"""
**{i}. {title}**
- **Authors:** {author_str}
- **Published:** {published}
- **Categories:** {category_str}
- **ArXiv ID:** {arxiv_id}
- **URL:** {arxiv_url}
- **PDF:** {pdf_url}
- **Abstract:** {summary[:300]}{'...' if len(summary) > 300 else ''}

---
"""
                results.append(paper_info)
            
            return f"Found {len(feed.entries)} papers for '{query}':\n\n" + "\n".join(results)
            
        except Exception as e:
            return f"Error searching for papers: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Search web for papers on a topic using Perplexity", icon="globe")
    @hyphae.args(query="The research topic or query to search for")
    def SearchWebPapers(self, query: str) -> str:
        """Use Perplexity to search for academic papers on a topic"""
        search_query = f"academic papers research {query} arxiv site:arxiv.org"
        return PerplexitySearcher().run(search_query)
    
    @hyphae.tool("Search for papers beyond ArXiv (Semantic Scholar)", icon="doc.plaintext")
    @hyphae.args(
        query="The search query (can be topic, keywords, or title)",
        max_results="Maximum number of results to return (default: 10)",
        offset="Offset for pagination when retrieving additional results"
    )
    def SearchExternalPapers(self, query: str, max_results: int = 10, offset: int = 0) -> str:
        """Searches Semantic Scholar for papers matching the query.

        Returns a formatted markdown string similar to the ArXiv search output but **without** citation metrics.
        """

        # Prepare request
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TruffleBot/1.0; +https://truffles.ai)"
        }
        url = "https://api.semanticscholar.org/graph/v1/paper/search"

        fields = [
            "title",
            "authors",
            "year",
            "venue",
            "journal",
            "externalIds",
            "fieldsOfStudy",
            "url",
            "abstract",
            "tldr"
        ]

        params = {
            "query": query,
            "limit": min(max_results, 100),
            "offset": offset,
            "fields": ",".join(fields)
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json().get("data", [])

            if not data:
                return f"No external papers found for query: {query}"

            results = []
            for i, paper in enumerate(data, 1):
                title = paper.get("title", "No title").replace("\n", " ").strip()
                authors = [a.get("name", "Unknown") for a in paper.get("authors", [])]
                author_str = ", ".join(authors[:3]) if authors else "Unknown"
                if len(authors) > 3:
                    author_str += " et al."

                year = paper.get("year", "n.d.")
                venue = paper.get("venue") or (paper.get("journal", {}).get("name") if paper.get("journal") else "")
                venue = venue if venue else "Unknown"

                url_link = paper.get("url", "")
                external_ids = paper.get("externalIds", {})
                doi = external_ids.get("DOI", "")

                abstract = paper.get("abstract") or paper.get("tldr", {}).get("text", "") or "No abstract available."

                fields_of_study = paper.get("fieldsOfStudy", [])
                fields_str = ", ".join(fields_of_study[:3])

                info = f"""
**{i}. {title} ({year})**
- **Authors:** {author_str}
- **Venue:** {venue}
- **Fields:** {fields_str}
- **URL:** {url_link}
- **DOI:** {doi}
- **Abstract:** {abstract[:300]}{'...' if len(abstract) > 300 else ''}

---
"""
                results.append(info)

            return f"Found {len(data)} external papers for '{query}':\n\n" + "\n".join(results)

        except Exception as e:
            return f"Error searching external papers: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Select a paper to discuss by providing its ArXiv ID", icon="doc.text")
    @hyphae.args(
        arxiv_id="The ArXiv ID of the paper (e.g., '2301.12345' or 'cs.AI/0601001')",
        load_full_text="Whether to attempt to load the full paper text for deeper analysis"
    )
    def SelectPaper(self, arxiv_id: str, load_full_text: bool = True) -> str:
        """Select a paper for discussion and load its content"""
        
        # Clean the ArXiv ID
        arxiv_id = arxiv_id.strip()
        if arxiv_id.startswith('http'):
            # Extract ID from URL
            arxiv_id = arxiv_id.split('/')[-1]
            arxiv_id = arxiv_id.replace('.pdf', '')
        
        try:
            # Get paper metadata
            base_url = "http://export.arxiv.org/api/query"
            search_query = f"id_list={arxiv_id}"
            url = f"{base_url}?{search_query}"
            
            response = requests.get(url)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"Paper with ID '{arxiv_id}' not found."
            
            entry = feed.entries[0]
            
            # Store paper information
            self.selected_paper = {
                'id': arxiv_id,
                'title': entry.title.replace('\n', ' ').strip(),
                'authors': [author.name for author in entry.authors] if hasattr(entry, 'authors') else [],
                'abstract': entry.summary.replace('\n', ' ').strip(),
                'published': entry.published[:10] if hasattr(entry, 'published') else "Unknown",
                'categories': [tag.term for tag in entry.tags] if hasattr(entry, 'tags') else [],
                'url': f"https://arxiv.org/abs/{arxiv_id}",
                'pdf_url': f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            }
            
            # Attempt to get full text if requested
            paper_text = ""
            if load_full_text:
                try:
                    paper_text = self._extract_paper_text(arxiv_id)
                    self.paper_content = paper_text
                except Exception as e:
                    paper_text = f"Could not extract full text: {str(e)}"
            
            # Format response
            authors_str = ", ".join(self.selected_paper['authors'][:3])
            if len(self.selected_paper['authors']) > 3:
                authors_str += " et al."
            
            result = f"""
**Paper Selected Successfully!**

**Title:** {self.selected_paper['title']}
**Authors:** {authors_str}
**Published:** {self.selected_paper['published']}
**Categories:** {', '.join(self.selected_paper['categories'][:3])}
**URL:** {self.selected_paper['url']}
**PDF URL:** {self.selected_paper['pdf_url']}

**Abstract:**
{self.selected_paper['abstract']}

**Status:** Paper is now loaded and ready for discussion. You can now use your Researcher to ask questions about this specific paper!
"""
            
            if paper_text and "Could not extract" not in paper_text:
                result += f"\n**Full Text Status:** Successfully loaded full paper content for detailed analysis."
            else:
                result += f"\n**Full Text Status:**  Using abstract and metadata only. {paper_text if paper_text else ''}"
            
            return result
            
        except Exception as e:
            return f"Error selecting paper: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    def _extract_paper_text(self, arxiv_id: str) -> str:

        try:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            response = requests.get(abs_url)
            
            if response.status_code == 200:
                content = response.text
                
                return f"Paper abstract page loaded. For full text analysis, the abstract and metadata provide substantial information for discussion."
            else:
                return "Could not access paper content"
                
        except Exception as e:
            return f"Error extracting paper text: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Researcher - Discuss the selected paper with an expert", icon="graduationcap", predicate=lambda self: self.has_paper_selected())
    @hyphae.args(
        question="Your question about the selected paper",
        analysis_type="Type of analysis: 'general', 'technical', 'methodology', 'results', 'implications'"
    )
    def Researcher(self, question: str, analysis_type: str = "general") -> str:
      
        
        if not self.selected_paper:
            return "No paper selected! Please use the SelectPaper tool first to choose a paper to discuss."
        
        paper_info = f"""
Paper: {self.selected_paper['title']}
Authors: {', '.join(self.selected_paper['authors'])}
Published: {self.selected_paper['published']}
Categories: {', '.join(self.selected_paper['categories'])}
ID: {self.selected_paper['id']}

Abstract:
{self.selected_paper['abstract']}
"""
        
        if self.paper_content and "Could not extract" not in self.paper_content:
            paper_info += f"\n\nAdditional Content:\n{self.paper_content[:2000]}..."
        
        researcher_prompt = f"""You are an expert academic researcher with deep knowledge across multiple fields. A user has selected this research paper to discuss:

{paper_info}

The user is asking about this paper with a focus on {analysis_type} analysis. Please provide a thorough, educational response that:

1. Directly addresses their question about the paper
2. Provides context and background when helpful
3. Explains complex concepts in an accessible way
4. Relates the paper to broader research trends when relevant
5. Suggests follow-up questions or areas for deeper exploration

user's question: {question}

Please respond as a knowledgeable researcher would, being both informative and encouraging."""

        try:
            response = PerplexitySearcher().run(researcher_prompt)
            
            return f" **Researcher's Response:**\n\n{response}\n\n---\n **Current Paper:** {self.selected_paper['title']}\n **Url:** {self.selected_paper['url']}"
            
        except Exception as e:
            return f"Error getting researcher response: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Get information about the currently selected paper", icon="info.circle", predicate=lambda self: self.has_paper_selected())
    def GetCurrentPaper(self) -> str:
        
        if not self.selected_paper:
            return "No paper is currently selected. Use SearchPapers to find papers, then SelectPaper to choose one."
        
        authors_str = ", ".join(self.selected_paper['authors'])
        categories_str = ", ".join(self.selected_paper['categories'])
        
        return f"""
**Currently Selected Paper:**

**Title:** {self.selected_paper['title']}
**Authors:** {authors_str}
**Published:** {self.selected_paper['published']}
**Categories:** {categories_str}
**ID:** {self.selected_paper['id']}
**URL:** {self.selected_paper['url']}
**PDF:** {self.selected_paper['pdf_url']}

**Abstract:**
{self.selected_paper['abstract']}

"""

def on_app_start(instance: ArxivApp):
    print("ArxivApp starting")

hooks.on_app_start = on_app_start

if __name__ == "__main__":
    hyphae.run(ArxivApp())
