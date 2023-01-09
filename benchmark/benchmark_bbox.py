from __future__ import division, print_function

import argparse
import math
import os
import sys
from abc import ABC
from collections import defaultdict
from timeit import Timer

import cv2
import numpy as np
import pandas as pd
import pkg_resources
from imgaug import augmenters as iaa
from imgaug.augmentables.bbs import BoundingBox, BoundingBoxesOnImage
from pytablewriter import MarkdownTableWriter
from pytablewriter.style import Style
from tqdm import tqdm

import albumentations as A

cv2.setNumThreads(0)  # noqa E402
cv2.ocl.setUseOpenCL(False)  # noqa E402

os.environ["OMP_NUM_THREADS"] = "1"  # noqa E402
os.environ["OPENBLAS_NUM_THREADS"] = "1"  # noqa E402
os.environ["MKL_NUM_THREADS"] = "1"  # noqa E402
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"  # noqa E402
os.environ["NUMEXPR_NUM_THREADS"] = "1"  # noqa E402


DEFAULT_BENCHMARKING_LIBRARIES = [
    "albumentations",
    "imgaug",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Augmentation libraries performance benchmark")
    parser.add_argument(
        "-l", "--libraries", default=DEFAULT_BENCHMARKING_LIBRARIES, nargs="+", help="list of libraries to benchmark"
    )
    parser.add_argument(
        "-r", "--runs", default=5, type=int, metavar="N", help="number of runs for each benchmark (default: 5)"
    )
    parser.add_argument(
        "--show-std", dest="show_std", action="store_true", help="show standard deviation for benchmark runs"
    )
    parser.add_argument("-p", "--print-package-versions", action="store_true", help="print versions of packages")
    parser.add_argument("-m", "--markdown", action="store_true", help="print benchmarking results as a markdown table")
    return parser.parse_args()


def get_package_versions():
    packages = [
        "albumentations",
        "imgaug",
    ]
    package_versions = {"Python": sys.version}
    for package in packages:
        try:
            package_versions[package] = pkg_resources.get_distribution(package).version
        except pkg_resources.DistributionNotFound:
            pass
    return package_versions


class MarkdownGenerator:
    def __init__(self, df, package_versions):
        self._df = df
        self._package_versions = package_versions
        self._libraries_description = {"torchvision": "(Pillow-SIMD backend)"}

    def _highlight_best_result(self, results):
        best_result = float("-inf")
        for result in results:
            try:
                result = int(result)
            except ValueError:
                continue
            if result > best_result:
                best_result = result
        return ["**{}**".format(r) if r == str(best_result) else r for r in results]

    def _make_headers(self):
        libraries = self._df.columns.to_list()
        columns = []
        for library in libraries:
            version = self._package_versions[library]
            library_description = self._libraries_description.get(library)
            if library_description:
                library += " {}".format(library_description)

            columns.append("{library}<br><small>{version}</small>".format(library=library, version=version))
        return [""] + columns

    def _make_value_matrix(self):
        index = self._df.index.tolist()
        values = self._df.values.tolist()
        value_matrix = []
        for transform, results in zip(index, values):
            row = [transform] + self._highlight_best_result(results)
            value_matrix.append(row)
        return value_matrix

    def _make_versions_text(self):
        libraries = ["Python", "numpy", "pillow-simd", "opencv-python", "scikit-image", "scipy"]
        libraries_with_versions = [
            "{library} {version}".format(library=library, version=self._package_versions[library].replace("\n", ""))
            for library in libraries
        ]
        return "Python and library versions: {}.".format(", ".join(libraries_with_versions))

    def print(self):
        writer = MarkdownTableWriter()
        writer.headers = self._make_headers()
        writer.value_matrix = self._make_value_matrix()
        writer.styles = [Style(align="left")] + [Style(align="center") for _ in range(len(writer.headers) - 1)]
        writer.write_table()
        print("\n" + self._make_versions_text())


def read_img_cv2(img_size=(512, 512, 3)):
    img = np.zeros(shape=img_size, dtype=np.uint8)
    return img


def generate_random_bboxes(bbox_nums: int = 1):
    return np.random.random(size=(bbox_nums, 4))


def format_results(images_per_second_for_aug, show_std=False):
    if images_per_second_for_aug is None:
        return "-"
    result = str(math.floor(np.mean(images_per_second_for_aug)))
    if show_std:
        result += " ± {}".format(math.ceil(np.std(images_per_second_for_aug)))
    return result


class BenchmarkTest(ABC):
    def __str__(self):
        return self.__class__.__name__

    def imgaug(self, img):
        return self.imgaug_transform.augment_image(img)

    def is_supported_by(self, library):
        if library == "imgaug":
            return hasattr(self, "imgaug_transform")
        return hasattr(self, library)

    def run(self, library, imgs: np.ndarray, bboxes: np.ndarray):
        transform = getattr(self, library)
        for img in imgs:
            transform(img)


class HorizontalFlip(BenchmarkTest):
    def __init__(self):
        self.imgaug_transform = iaa.Fliplr(p=1)

    def albumentations(self, img):

        if img.ndim == 3 and img.shape[2] > 1 and img.dtype == np.uint8:
            return A.hflip_cv2(img)
        return A.hflip(img)

    def imgaug(self, img):
        return np.ascontiguousarray(self.imgaug_transform.augment_image(img))


def main():
    args = parse_args()
    package_versions = get_package_versions()
    if args.print_package_versions:
        print(package_versions)
    images_per_second = defaultdict(dict)
    libraries = args.libraries

    benchmarks = [
        HorizontalFlip(),
        # VerticalFlip(),
        # Rotate(),
        # ShiftScaleRotate(),
        # Brightness(),
        # Contrast(),
        # BrightnessContrast(),
        # ShiftRGB(),
        # ShiftHSV(),
        # Gamma(),
        # Grayscale(),
        # RandomCrop64(),
        # PadToSize512(),
        # Resize512(),
        # RandomSizedCrop_64_512(),
        # Posterize(),
        # Solarize(),
        # Equalize(),
        # Multiply(),
        # MultiplyElementwise(),
        # ColorJitter(),
    ]
    for library in libraries:
        imgs = read_img_cv2(img_size=(512, 512, 3))
        pbar = tqdm(total=len(benchmarks))
        for benchmark in benchmarks:
            pbar.set_description("Current benchmark: {} | {}".format(library, benchmark))
            benchmark_images_per_second = None
            if benchmark.is_supported_by(library):
                timer = Timer(lambda: benchmark.run(library, imgs))
                run_times = timer.repeat(number=1, repeat=args.runs)
                benchmark_images_per_second = [1 / (run_time / args.images) for run_time in run_times]
            images_per_second[library][str(benchmark)] = benchmark_images_per_second
            pbar.update(1)
        pbar.close()
    pd.set_option("display.width", 1000)
    df = pd.DataFrame.from_dict(images_per_second)
    df = df.applymap(lambda r: format_results(r, args.show_std))
    df = df[libraries]
    augmentations = [str(i) for i in benchmarks]
    df = df.reindex(augmentations)
    if args.markdown:
        makedown_generator = MarkdownGenerator(df, package_versions)
        makedown_generator.print()
    else:
        print(df.head(len(augmentations)))


if __name__ == "__main__":
    main()
