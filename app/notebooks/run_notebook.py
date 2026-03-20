import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: poetry run run-notebook <notebook_path>")
        sys.exit(1)

    notebook_path = sys.argv[1]
    with open(notebook_path) as f:
        nb = nbformat.read(f, as_version=4)

    ep = ExecutePreprocessor(timeout=600, kernel_name='python3')
    ep.preprocess(nb, {'metadata': {'path': '.'}})

    output_path = notebook_path.replace('.py', '_executed.ipynb')
    with open(output_path, 'w') as f:
        nbformat.write(nb, f)

    print(f"Executed notebook saved to: {output_path}")


if __name__ == "__main__":
    main()
