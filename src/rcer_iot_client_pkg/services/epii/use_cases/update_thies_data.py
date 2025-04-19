from dotenv import load_dotenv

import rcer_iot_client_pkg.services.epii.constants.update_thies_data_constants as c
from rcer_iot_client_pkg.general_types.error_types.api.update_thies_data_error_types import (
    FetchCloudFileNamesError,
    FetchThiesFileContentError,
    ThiesUploadEmptyError,
)
from rcer_iot_client_pkg.general_types.error_types.common import (
    EmptyDataError,
    FtpClientError,
    SharepointClientError,
)
from rcer_iot_client_pkg.libs.ftp_client import (
    FTPClient,
    FtpClientInitArgs,
    FtpListFilesArgs,
    FtpReadFileArgs,
)
from rcer_iot_client_pkg.libs.sharepoint_client import (
    SharepointClient,
    SharepointClientInitArgs,
    SpListFilesArgs,
)
from rcer_iot_client_pkg.services.epii.use_cases.types import (
    UpdateThiesDataUseCaseInput,
)
from rcer_iot_client_pkg.services.epii.utils import (
    generate_file_content,
)

load_dotenv()


class UpdateThiesDataUseCase:
    def __init__(self, input: UpdateThiesDataUseCaseInput):
        self.ftp_port = input.ftp_port
        self.ftp_host = input.ftp_host
        self.ftp_password = input.ftp_password
        self.ftp_user = input.ftp_user
        self.sharepoint_client = self._initialize_sharepoint_client()
        self.thies_ftp_client = self._initialize_thies_ftp_client()
        self.uploading = set()

    def _initialize_sharepoint_client(self) -> SharepointClient:
        """Initialize the HTTP client."""
        try:
            return SharepointClient(
                SharepointClientInitArgs(client_name="aiohttp_client")
            )
        except ConnectionError as error:
            raise SharepointClientError(error)

    def _initialize_thies_ftp_client(self) -> FTPClient:
        """Initialize the FTP client."""
        try:
            return FTPClient(
                FtpClientInitArgs(
                    client_name="aioftp_client",
                    host=self.ftp_host,
                    user=self.ftp_user,
                    password=self.ftp_password,
                    port=self.ftp_port,
                )
            )
        except RuntimeError as error:
            raise FtpClientError(error)

    async def fetch_cloud_file_names(self) -> set[str]:
        """Fetch file names from the RCER cloud."""

        try:
            cloud_files = set()
            async with self.sharepoint_client:
                for folder in c.SHAREPOINT_THIES_FOLDERS:
                    args = SpListFilesArgs(
                        folder_relative_url=f"{c.SHAREPOINT_BASE_URL}/{folder}"
                    )
                    files = await self.sharepoint_client.list_files(args)
                    cloud_files.update(
                        {f"{folder}_{item['Name']}" for item in files["value"]}
                    )
            return cloud_files
        except ConnectionError as error:
            raise FetchCloudFileNamesError(error)

    async def fetch_thies_file_names(self) -> set[str]:
        """Fetch file names from the THIES FTP server."""
        try:
            avg_files = await self.thies_ftp_client.list_files(
                FtpListFilesArgs(path=c.FTP_SERVER_PATH_AVG_FILES)
            )
            ext_files = await self.thies_ftp_client.list_files(
                FtpListFilesArgs(path=c.FTP_SERVER_PATH_EXT_FILES)
            )
            return {f"AVG_{name}" for name in avg_files} | {
                f"EXT_{name}" for name in ext_files
            }
        except ConnectionError:
            raise ThiesUploadEmptyError

    async def fetch_thies_file_content(self) -> dict[str, bytes]:
        """Fetch the content of files from the THIES FTP server."""
        content_files = {}
        for file in self.uploading:
            try:
                origin, filename = file.split("_", 1)
                file_path = (
                    f"{c.PATH_AVG_FILES}/{filename}"
                    if origin == "AVG"
                    else f"{c.PATH_EXT_FILES}/{filename}"
                )
                content = await self.thies_ftp_client.read_file(
                    FtpReadFileArgs(file_path)
                )
                content_files[filename] = content
            except ConnectionError as error:
                raise FetchThiesFileContentError(error)
        return content_files

    async def execute(self) -> dict:
        """Synchronize data from the THIES Center to the cloud."""
        try:
            thies_files = await self.fetch_thies_file_names()
        except RuntimeError as error:
            raise FtpClientError(error)

        cloud_files = await self.fetch_cloud_file_names()
        self.uploading = thies_files - cloud_files
        if not self.uploading:
            raise EmptyDataError

        thies_file_contents = await self.fetch_thies_file_content()
        data = generate_file_content(thies_file_contents)
        return data
