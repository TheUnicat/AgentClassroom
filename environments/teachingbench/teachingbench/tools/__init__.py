from teachingbench.tools.image_gen import image_gen

# Verifiers builds tool_defs by calling `convert_func_to_tool_def` on each callable here,
# so this list is the env's tool registry.
TOOLS = [image_gen]

__all__ = ["TOOLS", "image_gen"]
