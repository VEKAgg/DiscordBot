import os
import re
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CogFixer')

def fix_cog_setup(file_path):
    """Fix the setup function in a cog file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Check if the file has a setup function
        setup_pattern = r'async\s+def\s+setup\s*\(\s*bot\s*\)\s*:'
        if not re.search(setup_pattern, content):
            logger.warning(f"No setup function found in {file_path}")
            return False
        
        # Find the setup function and its body
        setup_match = re.search(r'(async\s+def\s+setup\s*\(\s*bot\s*\)\s*:.*?)(async|\Z)', content, re.DOTALL)
        if not setup_match:
            logger.warning(f"Could not parse setup function in {file_path}")
            return False
        
        setup_content = setup_match.group(1)
        
        # Check if the setup function already has the if bot is not None check
        if 'if bot is not None' in setup_content:
            logger.info(f"Setup function in {file_path} already fixed")
            return False
        
        # Extract the cog class name
        cog_class_match = re.search(r'class\s+(\w+)\s*\(\s*commands\.Cog\s*\)', content)
        if not cog_class_match:
            logger.warning(f"Could not find cog class in {file_path}")
            return False
        
        cog_class_name = cog_class_match.group(1)
        
        # Create the new setup function
        new_setup = f"""async def setup(bot):
    \"\"\"Setup the {cog_class_name} cog\"\"\"
    if bot is not None:
        await bot.add_cog({cog_class_name}(bot))
        logging.getLogger('VEKA').info("{cog_class_name} cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in {cog_class_name} cog setup")
"""
        
        # Replace the old setup function with the new one
        new_content = re.sub(setup_pattern + r'.*?(async|\Z)', new_setup, content, flags=re.DOTALL)
        
        # Write the updated content back to the file
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(new_content)
        
        logger.info(f"Fixed setup function in {file_path}")
        return True
    
    except Exception as e:
        logger.error(f"Error fixing {file_path}: {str(e)}")
        return False

def fix_all_cogs():
    """Fix all cog files in the project"""
    fixed_count = 0
    
    # Fix cogs in the main cogs directory
    cogs_dir = './src/cogs'
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and not filename.startswith('__'):
            file_path = os.path.join(cogs_dir, filename)
            if fix_cog_setup(file_path):
                fixed_count += 1
    
    # Fix cogs in subdirectories
    cog_subdirs = ['workshops', 'portfolio', 'gamification']
    for subdir in cog_subdirs:
        subdir_path = os.path.join(cogs_dir, subdir)
        if os.path.exists(subdir_path):
            for filename in os.listdir(subdir_path):
                if filename.endswith('.py') and not filename.startswith('__'):
                    file_path = os.path.join(subdir_path, filename)
                    if fix_cog_setup(file_path):
                        fixed_count += 1
    
    return fixed_count

if __name__ == '__main__':
    fixed_count = fix_all_cogs()
    logger.info(f"Fixed {fixed_count} cog files") 