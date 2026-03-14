import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace focus:ring- colors
content = re.sub(r'focus:ring-teal-\d+/\d+', 'focus:ring-[#22A087]/20', content)
content = re.sub(r'focus:ring-teal-\d+', 'focus:ring-[#22A087]', content)
content = re.sub(r'focus:ring-brand-\d+', 'focus:ring-[#22A087]', content)

# Replace focus:border- colors
content = re.sub(r'focus:border-teal-\d+', 'focus:border-[#22A087]', content)
content = re.sub(r'focus:border-brand-\d+', 'focus:border-[#22A087]', content)

# Replace hover:border- colors
content = re.sub(r'hover:border-teal-\d+', 'hover:border-[#22A087]', content)
content = re.sub(r'hover:border-brand-\d+', 'hover:border-[#22A087]', content)
content = re.sub(r'hover:border-gray-300', 'hover:border-[#22A087]', content)

# Add any missing hover:ring-1 hover:ring-[#22A087] where it just had hover:border-[#22A087] for solid 2px-like contrast (optional)
# But since user wants full visual consistency, we can leave the base as hover:border-[#22A087] which is consistent.

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully replaced all interaction colors!")
